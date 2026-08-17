from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from navaero_transition_model.core.case_inputs.scenario_table import DEFAULT_SCENARIO_ID
from navaero_transition_model.core.decision_logic.base import (
    DECISION_ATTITUDE_DEFAULT_MODE,
    DECISION_ATTITUDES,
    DECISION_MODES,
    CandidateEvaluation,
    clean_scope_value,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityCargoLogic,
    LegacyWeightedUtilityLogic,
    LegacyWeightedUtilityMaritimeCargoLogic,
    LegacyWeightedUtilityMaritimePassengerLogic,
)
from navaero_transition_model.core.decision_logic.loss_law_robust import (
    AmbiguityRobustNoValidCandidatesError,
    ProbabilityBounds,
    belief_set_probability_vector,
    construct_probability_bounds,
    load_belief_set_probabilities,
    mean_probability_vector,
    score_ambiguity_aware_decisions,
    select_ambiguity_aware_decision,
)

if TYPE_CHECKING:
    from navaero_transition_model.core.agent_types.aviation_cargo_airline import (
        AviationCargoAirlineAgent,
    )
    from navaero_transition_model.core.agent_types.aviation_passenger_airline import (
        AviationPassengerAirlineAgent,
    )
    from navaero_transition_model.core.agent_types.maritime_cargo_shipline import (
        MaritimeCargoShiplineAgent,
    )
    from navaero_transition_model.core.agent_types.maritime_passenger_shipline import (
        MaritimePassengerShiplineAgent,
    )


@dataclass(frozen=True)
class ScenarioCandidateOutcome:
    scenario_id: str
    probability: float
    score: float
    evaluation: CandidateEvaluation | None


@dataclass(frozen=True)
class CandidateAggregate:
    technology_row: pd.Series
    outcomes: tuple[ScenarioCandidateOutcome, ...]
    expected_utility: float
    robust_score: float
    worst_case_utility: float
    expected_shortfall_utility: float
    worst_case_expected_shortfall_utility: float
    decision_key: str = ""
    action: str = "invest"


class AmbiguityAwareSelectionMixin:
    """Scenario-set scoring shared by ambiguity-aware decision logic classes."""

    def _uses_loss_law_robust_selection(self, agent) -> bool:
        del agent
        return True

    def _loss_law_probability_inputs(self, agent) -> tuple[pd.DataFrame, ProbabilityBounds]:
        model = agent.model
        cached_bounds = getattr(model, "_ambiguity_loss_law_probability_bounds", None)
        cached_probabilities = getattr(model, "_ambiguity_loss_law_probabilities", None)
        if cached_bounds is not None and cached_probabilities is not None:
            return cached_probabilities, cached_bounds

        config = model.scenario.ambiguity_aware_decision
        probability_table_path = config.probability_table_path(model.scenario.base_path)
        if probability_table_path is None:
            raise ValueError(
                "ambiguity_aware_decision.probability_table is required for "
                "investment_logic=ambiguity_aware_utility",
            )
        probabilities = load_belief_set_probabilities(
            probability_table_path,
            belief_sets=config.belief_sets,
            input_format=config.probability_input_format,
            tolerance=config.probability_tolerance,
        )
        bounds = construct_probability_bounds(
            probabilities,
            tolerance=config.probability_tolerance,
        )
        model._ambiguity_loss_law_probabilities = probabilities
        model._ambiguity_loss_law_probability_bounds = bounds
        if config.write_debug_outputs:
            model.record_ambiguity_probability_bounds(bounds.to_frame().to_dict("records"))
        return probabilities, bounds

    def _loss_law_probability_bounds(self, agent) -> ProbabilityBounds:
        return self._loss_law_probability_inputs(agent)[1]

    def _decision_mode(self, agent) -> str:
        """Resolve the effective NPV-selection rule for this decision.

        `decision_mode` (precise, e.g. risk_averse_mean) is authoritative when
        set. Otherwise it is derived from `decision_attitude` (coarse label,
        e.g. risk_averse), which may itself already be a precise mode name.
        Resolved fresh on every call rather than cached, so nothing here
        mutates the agent.
        """
        explicit_mode = str(getattr(agent, "decision_mode", "")).strip().lower()
        if explicit_mode in DECISION_MODES:
            return explicit_mode
        attitude = str(getattr(agent, "decision_attitude", "risk_neutral")).strip().lower()
        derived = DECISION_ATTITUDE_DEFAULT_MODE.get(attitude, attitude)
        return derived if derived in DECISION_MODES else "risk_neutral"

    def _scenario_probabilities(self, agent) -> dict[str, float]:
        config = agent.model.scenario.ambiguity_aware_decision
        if not config.enabled:
            return {DEFAULT_SCENARIO_ID: 1.0}
        return {
            scenario_id: float(config.probabilities[scenario_id])
            for scenario_id in config.scenario_ids
        }

    @contextmanager
    def _scenario_context(self, agent, scenario_id: str, year: int):
        previous_scenario = getattr(agent, "_active_decision_scenario_id", None)
        previous_year = getattr(agent, "_active_decision_year", None)
        agent._active_decision_scenario_id = scenario_id
        agent._active_decision_year = year
        try:
            yield
        finally:
            agent._active_decision_scenario_id = previous_scenario
            agent._active_decision_year = previous_year

    def _decision_score(self, evaluation: CandidateEvaluation) -> float:
        # The ambiguity-aware v1 selection criterion intentionally uses economic
        # utility as the dominant score; legacy environmental/policy components
        # remain available through legacy calculations and output diagnostics.
        return float(evaluation.economic_utility)

    def _weighted_expected_score(self, outcomes: Iterable[ScenarioCandidateOutcome]) -> float:
        return sum(outcome.probability * outcome.score for outcome in outcomes)

    def _expected_shortfall_score(
        self,
        outcomes: Iterable[ScenarioCandidateOutcome],
        alpha: float,
    ) -> float:
        """Probability-weighted mean utility over the worst alpha probability mass."""
        remaining_tail = max(min(float(alpha), 1.0), 1e-9)
        sorted_outcomes = sorted(outcomes, key=lambda outcome: outcome.score)
        weighted_sum = 0.0
        consumed = 0.0
        for outcome in sorted_outcomes:
            take = min(outcome.probability, remaining_tail - consumed)
            if take <= 0.0:
                break
            weighted_sum += take * outcome.score
            consumed += take
        if consumed <= 0.0:
            return sorted_outcomes[0].score if sorted_outcomes else 0.0
        return weighted_sum / consumed

    def _worst_case_expected_score(
        self,
        outcomes: Iterable[ScenarioCandidateOutcome],
        probability_deviation: float,
    ) -> float:
        """Worst-case expected utility under bounded probability ambiguity."""
        outcome_list = list(outcomes)
        if not outcome_list:
            return 0.0
        q = self._worst_case_probabilities(outcome_list, probability_deviation)
        return sum(q[outcome.scenario_id] * outcome.score for outcome in outcome_list)

    def _worst_case_probabilities(
        self,
        outcomes: Iterable[ScenarioCandidateOutcome],
        probability_deviation: float,
    ) -> dict[str, float]:
        outcome_list = list(outcomes)
        if not outcome_list:
            return {}
        delta = max(float(probability_deviation), 0.0)
        lower_bounds = {
            outcome.scenario_id: max(0.0, outcome.probability - delta) for outcome in outcome_list
        }
        upper_bounds = {
            outcome.scenario_id: min(1.0, outcome.probability + delta) for outcome in outcome_list
        }
        q = dict(lower_bounds)
        remaining = max(1.0 - sum(q.values()), 0.0)
        for outcome in sorted(outcome_list, key=lambda item: item.score):
            room = max(upper_bounds[outcome.scenario_id] - q[outcome.scenario_id], 0.0)
            take = min(room, remaining)
            q[outcome.scenario_id] += take
            remaining -= take
            if remaining <= 1e-12:
                break
        if remaining > 1e-9:
            total = sum(q.values()) or 1.0
            q = {scenario_id: value / total for scenario_id, value in q.items()}
        return q

    def _worst_case_expected_shortfall_score(
        self,
        outcomes: Iterable[ScenarioCandidateOutcome],
        alpha: float,
        probability_deviation: float,
    ) -> float:
        outcome_list = list(outcomes)
        q = self._worst_case_probabilities(outcome_list, probability_deviation)
        adjusted_outcomes = tuple(
            ScenarioCandidateOutcome(
                scenario_id=outcome.scenario_id,
                probability=q.get(outcome.scenario_id, outcome.probability),
                score=outcome.score,
                evaluation=outcome.evaluation,
            )
            for outcome in outcome_list
        )
        return self._expected_shortfall_score(adjusted_outcomes, alpha)

    def _candidate_aggregate(
        self,
        agent,
        technology_row: pd.Series,
        outcomes: tuple[ScenarioCandidateOutcome, ...],
        *,
        decision_key: str | None = None,
        action: str = "invest",
    ) -> CandidateAggregate:
        config = agent.model.scenario.ambiguity_aware_decision
        expected = self._weighted_expected_score(outcomes)
        expected_shortfall = self._expected_shortfall_score(
            outcomes,
            config.expected_shortfall_alpha,
        )
        worst_case = self._worst_case_expected_score(outcomes, config.probability_deviation)
        worst_case_expected_shortfall = self._worst_case_expected_shortfall_score(
            outcomes,
            config.expected_shortfall_alpha,
            config.probability_deviation,
        )
        if agent.decision_attitude == "risk_averse":
            robust_score = expected_shortfall
        elif agent.decision_attitude == "ambiguity_averse":
            robust_score = (
                worst_case_expected_shortfall
                if config.robust_metric == "worst_case_expected_shortfall"
                else worst_case
            )
        else:
            robust_score = expected
        return CandidateAggregate(
            technology_row=technology_row,
            outcomes=outcomes,
            expected_utility=expected,
            robust_score=robust_score,
            worst_case_utility=worst_case,
            expected_shortfall_utility=expected_shortfall,
            worst_case_expected_shortfall_utility=worst_case_expected_shortfall,
            decision_key=decision_key or str(technology_row["technology_name"]),
            action=action,
        )

    def _evaluation_for_application(
        self,
        aggregate: CandidateAggregate,
    ) -> CandidateEvaluation | None:
        for outcome in aggregate.outcomes:
            if outcome.scenario_id == DEFAULT_SCENARIO_ID and outcome.evaluation is not None:
                return outcome.evaluation
        for outcome in aggregate.outcomes:
            if outcome.evaluation is not None:
                return outcome.evaluation
        return None

    def _frontier_rows(
        self,
        agent,
        asset: pd.Series,
        year: int,
        aggregates: list[CandidateAggregate],
        selected_key: str,
        selected_technology: str | None = None,
    ) -> list[dict[str, object]]:
        asset_id = asset.get("aircraft_id", asset.get("vessel_id", ""))
        if selected_technology is None:
            selected_technology = selected_key
        rows: list[dict[str, object]] = []
        for aggregate in aggregates:
            candidate_technology = str(aggregate.technology_row["technology_name"])
            for outcome in aggregate.outcomes:
                evaluation = outcome.evaluation
                rows.append(
                    {
                        "year": year,
                        "sector_name": agent.sector_name,
                        "application_name": agent.application_name,
                        "operator_name": agent.operator_name,
                        "operator_country": agent.operator_country,
                        "asset_id": asset_id,
                        "aircraft_id": asset_id if agent.sector_name == "aviation" else "",
                        "vessel_id": asset_id if agent.sector_name == "maritime" else "",
                        "segment": clean_scope_value(asset.get("segment", "")),
                        "decision_attitude": agent.decision_attitude,
                        "action": aggregate.action,
                        "selected_technology": selected_technology,
                        "candidate_technology": candidate_technology,
                        "scenario_id": outcome.scenario_id,
                        "scenario_probability": outcome.probability,
                        "candidate_utility": evaluation.total_utility if evaluation else None,
                        "candidate_economic_utility": (
                            evaluation.economic_utility if evaluation else None
                        ),
                        "candidate_payback_year": evaluation.payback_year if evaluation else None,
                        "candidate_operating_cost": (
                            evaluation.current_year_operating_cost if evaluation else None
                        ),
                        "candidate_npv": evaluation.net_present_value if evaluation else None,
                        "candidate_primary_energy": (
                            evaluation.primary_energy_quantity if evaluation else None
                        ),
                        "candidate_secondary_energy": (
                            evaluation.secondary_energy_quantity if evaluation else None
                        ),
                        "candidate_emissions": evaluation.total_emission if evaluation else None,
                        "expected_utility": aggregate.expected_utility,
                        "robust_score": aggregate.robust_score,
                        "worst_case_utility": aggregate.worst_case_utility,
                        "expected_shortfall_utility": aggregate.expected_shortfall_utility,
                        "worst_case_expected_shortfall_utility": (
                            aggregate.worst_case_expected_shortfall_utility
                        ),
                        "expected_shortfall_alpha": (
                            agent.model.scenario.ambiguity_aware_decision.expected_shortfall_alpha
                        ),
                        "selected_flag": aggregate.decision_key == selected_key,
                    },
                )
        return rows

    def _active_year(self, agent) -> int:
        active_year = getattr(agent, "_active_decision_year", None)
        if active_year is None:
            active_year = agent.current_year
        return int(active_year)

    def _scenario_clean_fuel_subsidy(self, agent, policy_signal) -> float:
        scenario_value = agent.scenario_value(
            "clean_fuel_subsidy",
            self._active_year(agent),
            default=None,
        )
        if scenario_value is None:
            return float(policy_signal.clean_fuel_subsidy)
        return float(scenario_value)

    def _nominal_probabilities_for_bounds(
        self,
        agent,
        bounds: ProbabilityBounds,
    ) -> dict[str, float] | None:
        probabilities, _ = self._loss_law_probability_inputs(agent)
        belief_set = agent.model.scenario.ambiguity_aware_decision.risk_neutral_belief_set
        if belief_set is not None:
            return belief_set_probability_vector(probabilities, belief_set)
        return mean_probability_vector(probabilities)

    def _asset_identifier(self, agent, asset: pd.Series) -> object:
        return asset.get("aircraft_id", asset.get("vessel_id", ""))

    def _loss_law_decision_row(
        self,
        agent,
        asset: pd.Series,
        year: int,
        technology_name: str,
        scenario_id: str,
        evaluation: CandidateEvaluation | None,
        reason: str = "",
    ) -> dict[str, object]:
        asset_id = self._asset_identifier(agent, asset)
        return {
            "operator_id": getattr(agent, "unique_id", agent.operator_name),
            "operator_name": agent.operator_name,
            "asset_id": asset_id,
            "aircraft_id": asset_id if agent.sector_name == "aviation" else "",
            "vessel_id": asset_id if agent.sector_name == "maritime" else "",
            "decision_year": year,
            "decision_id": technology_name,
            "technology_id": technology_name,
            "scenario_id": scenario_id,
            "npv": evaluation.net_present_value if evaluation is not None else pd.NA,
            "infeasible_reason": reason,
        }

    def _select_loss_law_robust_asset(
        self,
        agent,
        asset: pd.Series,
        year: int,
        initial_ets_balance: float | None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        config = agent.model.scenario.ambiguity_aware_decision
        decision_mode = self._decision_mode(agent)
        bounds = self._loss_law_probability_bounds(agent)
        nominal_probabilities = self._nominal_probabilities_for_bounds(agent, bounds)
        midpoint_probabilities = {
            scenario_id: (bounds.lower[scenario_id] + bounds.upper[scenario_id]) / 2.0
            for scenario_id in bounds.scenarios
        }
        midpoint_total = sum(midpoint_probabilities.values()) or 1.0
        midpoint_probabilities = {
            scenario_id: value / midpoint_total
            for scenario_id, value in midpoint_probabilities.items()
        }
        outcomes_by_technology: dict[str, tuple[ScenarioCandidateOutcome, ...]] = {}
        technology_rows: dict[str, pd.Series] = {}
        actions_by_technology: dict[str, str] = {}
        decision_rows: list[dict[str, object]] = []

        def _evaluate_candidate(
            decision_key: str,
            technology_row: pd.Series,
            action: str,
            evaluate_fn,
        ) -> None:
            technology_rows[decision_key] = technology_row
            actions_by_technology[decision_key] = action
            outcomes: list[ScenarioCandidateOutcome] = []
            for scenario_id in bounds.scenarios:
                probability = (
                    nominal_probabilities[scenario_id]
                    if nominal_probabilities is not None
                    else midpoint_probabilities[scenario_id]
                )
                with self._scenario_context(agent, scenario_id, year):
                    evaluation = None
                    score = 0.0
                    reason = ""
                    if self.is_candidate_available(
                        agent,
                        technology_row,
                        year,
                        str(asset["segment"]),
                    ):
                        evaluation = evaluate_fn()
                        score = self._decision_score(evaluation)
                    else:
                        reason = "candidate unavailable in scenario"
                decision_rows.append(
                    self._loss_law_decision_row(
                        agent,
                        asset,
                        year,
                        decision_key,
                        scenario_id,
                        evaluation,
                        reason,
                    ),
                )
                outcomes.append(
                    ScenarioCandidateOutcome(
                        scenario_id=scenario_id,
                        probability=float(probability),
                        score=score,
                        evaluation=evaluation,
                    ),
                )
            outcomes_by_technology[decision_key] = tuple(outcomes)

        is_planned = row_index is not None and not agent.fleet.planned_technology_choices(
            row_index,
            year,
        ).empty
        candidates = (
            agent.fleet.planned_technology_choices(row_index, year)
            if is_planned
            else agent.candidate_technology_rows(asset)
        )
        for _, technology_row in candidates.iterrows():
            technology_name = str(technology_row["technology_name"])
            _evaluate_candidate(
                technology_name,
                technology_row,
                "invest",
                lambda technology_row=technology_row: self.calc_payback_year(
                    agent,
                    asset,
                    technology_row,
                    year,
                    initial_ets_balance,
                ),
            )

        remaining_lifetime = int(asset["replacement_year"]) - year
        if (
            not is_planned
            and row_index is not None
            and agent.model.scenario.investment_timing.include_continue_option
            and remaining_lifetime > 0
        ):
            current_technology_row = agent.technology_row(str(asset["current_technology"]))
            continue_key = f"{current_technology_row['technology_name']}::continue"
            _evaluate_candidate(
                continue_key,
                current_technology_row,
                "continue_current",
                lambda: self.evaluate_continue_current(
                    agent,
                    asset,
                    year,
                    initial_ets_balance,
                ),
            )

        decision_frame = pd.DataFrame(decision_rows)
        try:
            score_result = score_ambiguity_aware_decisions(
                decision_frame,
                bounds,
                decision_mode=decision_mode,
                tail_alpha=config.tail_alpha,
                representative_probabilities=nominal_probabilities,
                tolerance=config.probability_tolerance,
            )
        except AmbiguityRobustNoValidCandidatesError as exc:
            if not exc.excluded_candidates.empty:
                agent.model.record_ambiguity_excluded_candidates(
                    exc.excluded_candidates.to_dict("records"),
                )
            raise

        if not score_result.excluded_candidates.empty:
            agent.model.record_ambiguity_excluded_candidates(
                score_result.excluded_candidates.to_dict("records"),
            )
        agent.model.record_ambiguity_decision_scores(score_result.scores.to_dict("records"))
        agent.model.record_ambiguity_worst_case_probabilities(
            score_result.worst_case_probabilities.to_dict("records"),
        )
        agent.model.record_selected_ambiguity_decisions(score_result.selected.to_dict("records"))

        selected_decision = select_ambiguity_aware_decision(score_result)
        selected_key = str(selected_decision["technology_id"])
        selected_row = technology_rows[selected_key]
        selected_action = actions_by_technology[selected_key]
        selected_aggregate = self._candidate_aggregate(
            agent,
            selected_row,
            outcomes_by_technology[selected_key],
            decision_key=selected_key,
            action=selected_action,
        )
        selected_evaluation = self._evaluation_for_application(selected_aggregate)
        if selected_evaluation is None:
            raise ValueError(
                "Selected ambiguity-aware robust decision has no complete candidate evaluation",
            )

        aggregates = [
            self._candidate_aggregate(
                agent,
                technology_row,
                outcomes_by_technology[key],
                decision_key=key,
                action=actions_by_technology[key],
            )
            for key, technology_row in technology_rows.items()
        ]
        agent.model.record_robust_frontier(
            self._frontier_rows(
                agent,
                asset,
                year,
                aggregates,
                selected_key,
                str(selected_row["technology_name"]),
            ),
        )
        return selected_row, selected_evaluation, selected_action

    def _select_ambiguity_aware_asset(
        self,
        agent,
        asset: pd.Series,
        year: int,
        initial_ets_balance: float | None,
        fallback_selection,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        del fallback_selection
        if agent.decision_attitude not in DECISION_ATTITUDES:
            agent.decision_attitude = "risk_neutral"
        return self._select_loss_law_robust_asset(
            agent,
            asset,
            year,
            initial_ets_balance,
            row_index=row_index,
        )


class AmbiguityAwareUtilityLogic(AmbiguityAwareSelectionMixin, LegacyWeightedUtilityLogic):
    name = "ambiguity_aware_utility"

    def current_clean_fuel_subsidy(self, agent: AviationPassengerAirlineAgent) -> float:
        return self._scenario_clean_fuel_subsidy(
            agent,
            agent.model.current_policy_signal.aviation,
        )

    def select_technology_for_aircraft(
        self,
        agent: AviationPassengerAirlineAgent,
        aircraft: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        return self._select_ambiguity_aware_asset(
            agent,
            aircraft,
            year,
            initial_ets_balance,
            super().select_technology_for_aircraft,
            row_index=row_index,
        )


class AmbiguityAwareCargoLogic(AmbiguityAwareSelectionMixin, LegacyWeightedUtilityCargoLogic):
    name = AmbiguityAwareUtilityLogic.name

    def current_clean_fuel_subsidy(self, agent: AviationCargoAirlineAgent) -> float:
        return self._scenario_clean_fuel_subsidy(
            agent,
            agent.model.current_policy_signal.aviation,
        )

    def select_technology_for_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        # continue_current / planned-investment support is aviation-passenger only
        # for now; row_index is intentionally not threaded through here yet.
        return self._select_ambiguity_aware_asset(
            agent,
            aircraft,
            year,
            initial_ets_balance,
            super().select_technology_for_aircraft,
        )


class AmbiguityAwareMaritimeCargoLogic(
    AmbiguityAwareSelectionMixin,
    LegacyWeightedUtilityMaritimeCargoLogic,
):
    name = AmbiguityAwareUtilityLogic.name

    def current_clean_fuel_subsidy(self, agent: MaritimeCargoShiplineAgent) -> float:
        return self._scenario_clean_fuel_subsidy(
            agent,
            agent.model.current_policy_signal.maritime,
        )

    def select_technology_for_vessel(
        self,
        agent: MaritimeCargoShiplineAgent,
        vessel: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        # continue_current / planned-investment support is aviation-passenger only
        # for now; row_index is intentionally not threaded through here yet.
        return self._select_ambiguity_aware_asset(
            agent,
            vessel,
            year,
            initial_ets_balance,
            super().select_technology_for_vessel,
        )


class AmbiguityAwareMaritimePassengerLogic(
    AmbiguityAwareSelectionMixin,
    LegacyWeightedUtilityMaritimePassengerLogic,
):
    name = AmbiguityAwareUtilityLogic.name

    def current_clean_fuel_subsidy(self, agent: MaritimePassengerShiplineAgent) -> float:
        return self._scenario_clean_fuel_subsidy(
            agent,
            agent.model.current_policy_signal.maritime,
        )

    def select_technology_for_vessel(
        self,
        agent: MaritimePassengerShiplineAgent,
        vessel: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        # continue_current / planned-investment support is aviation-passenger only
        # for now; row_index is intentionally not threaded through here yet.
        return self._select_ambiguity_aware_asset(
            agent,
            vessel,
            year,
            initial_ets_balance,
            super().select_technology_for_vessel,
        )
