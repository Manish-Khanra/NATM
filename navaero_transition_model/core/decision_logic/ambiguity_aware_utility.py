from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from navaero_transition_model.core.case_inputs.scenario_table import DEFAULT_SCENARIO_ID
from navaero_transition_model.core.decision_logic.base import (
    DECISION_ATTITUDES,
    CandidateEvaluation,
    clean_scope_value,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityLogic,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility_cargo import (
    LegacyWeightedUtilityCargoLogic,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility_maritime_cargo import (
    LegacyWeightedUtilityMaritimeCargoLogic,
)

from .legacy_weighted_utility_maritime_passenger import LegacyWeightedUtilityMaritimePassengerLogic

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


class AmbiguityAwareSelectionMixin:
    """Scenario-set scoring shared by ambiguity-aware decision logic classes."""

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
            outcome.scenario_id: max(0.0, outcome.probability - delta)
            for outcome in outcome_list
        }
        upper_bounds = {
            outcome.scenario_id: min(1.0, outcome.probability + delta)
            for outcome in outcome_list
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
    ) -> CandidateAggregate:
        config = agent.model.scenario.ambiguity_aware_decision
        expected = self._weighted_expected_score(outcomes)
        expected_shortfall = self._expected_shortfall_score(
            outcomes,
            config.expected_shortfall_alpha,
        )
        worst_case = self._worst_case_expected_score(outcomes, config.probability_deviation)
        if agent.decision_attitude == "risk_averse":
            robust_score = expected_shortfall
        elif agent.decision_attitude == "ambiguity_averse":
            robust_score = (
                self._worst_case_expected_shortfall_score(
                    outcomes,
                    config.expected_shortfall_alpha,
                    config.probability_deviation,
                )
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
        selected_technology: str,
    ) -> list[dict[str, object]]:
        asset_id = asset.get("aircraft_id", asset.get("vessel_id", ""))
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
                        "selected_flag": candidate_technology == selected_technology,
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

    def _select_ambiguity_aware_asset(
        self,
        agent,
        asset: pd.Series,
        year: int,
        initial_ets_balance: float | None,
        fallback_selection,
    ) -> tuple[pd.Series, CandidateEvaluation]:
        if agent.decision_attitude not in DECISION_ATTITUDES:
            agent.decision_attitude = "risk_neutral"
        probabilities = self._scenario_probabilities(agent)
        aggregates: list[CandidateAggregate] = []
        for _, technology_row in agent.candidate_technology_rows(asset).iterrows():
            outcomes: list[ScenarioCandidateOutcome] = []
            for scenario_id, probability in probabilities.items():
                with self._scenario_context(agent, scenario_id, year):
                    evaluation = None
                    score = 0.0
                    # Scenario-specific availability and price/policy lookups are
                    # reached through agent.scenario_value while this context is active.
                    if self.is_candidate_available(
                        agent,
                        technology_row,
                        year,
                        str(asset["segment"]),
                    ):
                        evaluation = self.calc_payback_year(
                            agent,
                            asset,
                            technology_row,
                            year,
                            initial_ets_balance,
                        )
                        score = self._decision_score(evaluation)
                outcomes.append(
                    ScenarioCandidateOutcome(
                        scenario_id=scenario_id,
                        probability=probability,
                        score=score,
                        evaluation=evaluation,
                    ),
                )
            if any(outcome.evaluation is not None for outcome in outcomes):
                aggregates.append(
                    self._candidate_aggregate(agent, technology_row, tuple(outcomes)),
                )

        if not aggregates:
            return fallback_selection(agent, asset, year, initial_ets_balance)

        aggregates.sort(
            key=lambda aggregate: (
                aggregate.robust_score,
                aggregate.expected_utility,
                str(aggregate.technology_row["technology_name"]),
            ),
            reverse=True,
        )
        selected = aggregates[0]
        selected_technology = str(selected.technology_row["technology_name"])
        selected_evaluation = self._evaluation_for_application(selected)
        if selected_evaluation is None:
            return fallback_selection(agent, asset, year, initial_ets_balance)
        agent.model.record_robust_frontier(
            self._frontier_rows(agent, asset, year, aggregates, selected_technology),
        )
        return selected.technology_row, selected_evaluation


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
    ) -> tuple[pd.Series, CandidateEvaluation]:
        return self._select_ambiguity_aware_asset(
            agent,
            aircraft,
            year,
            initial_ets_balance,
            super().select_technology_for_aircraft,
        )


class AmbiguityAwareCargoLogic(AmbiguityAwareSelectionMixin, LegacyWeightedUtilityCargoLogic):
    name = "ambiguity_aware_utility_cargo"

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
    ) -> tuple[pd.Series, CandidateEvaluation]:
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
    name = "ambiguity_aware_utility_maritime_cargo"

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
    ) -> tuple[pd.Series, CandidateEvaluation]:
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
    name = "ambiguity_aware_utility_maritime_passenger"

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
    ) -> tuple[pd.Series, CandidateEvaluation]:
        return self._select_ambiguity_aware_asset(
            agent,
            vessel,
            year,
            initial_ets_balance,
            super().select_technology_for_vessel,
        )
