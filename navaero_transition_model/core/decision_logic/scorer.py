from __future__ import annotations

import pandas as pd

from navaero_transition_model.core.decision_logic.base import (
    CandidateEvaluation,
    OperationMetrics,
    clamp,
    clean_scope_value,
)


class NATMDecisionScorer:
    """Shared per-year replacement/growth/selection orchestration for every sector.

    Mirrors AURIS's split between a generic `AURISDecisionScorer` and small
    sector-specific plant classes: this mixin holds everything that is
    mechanically identical across aviation and maritime, passenger and cargo
    (which asset is due, how growth is sized against demand, how a candidate
    technology is ranked, how continue-vs-invest-vs-planned is decided). The
    genuinely different math per sector (revenue formulas, extra operating
    cost lines, environmental-utility/pollutant models) stays on each sector's
    own `Legacy*Logic` class, called here through a small set of hooks:

    - `_compute_revenue(agent, asset, technology_row, year)`
    - `_additional_operating_costs(revenue, technology_row)`
    - `_asset_capacity(agent, asset, technology_row, year)`
    - `_segment_capacity(agent, segment, year)`
    - `_allocated_demand(agent, segment, year)`
    - `_apply_technology(agent, row_index, technology_row, evaluation, year, *, action="invest")`
    - `_continue_operation(agent, row_index, evaluation, year)`
    - `_payback_year_fallback(life_time, max_npv_year)`

    plus four methods that are already uniformly named across every sector
    and are called directly with no adapter needed: `annual_operation_metrics`,
    `environmental_utility`, `is_candidate_available`, `current_clean_fuel_subsidy`.
    """

    def step(self, agent, year: int) -> None:
        agent.fleet.reset_actions()
        replacement_rows = self.replacement_row_indices(agent, year)
        agent.update_existing_fleet(year, excluded_indices=set(replacement_rows))
        self._replace_due_assets(agent, year, replacement_rows=replacement_rows)
        self._add_growth_assets(agent, year)

    def replacement_row_indices(self, agent, year: int) -> list[int]:
        clean_fuel_subsidy = self.current_clean_fuel_subsidy(agent)
        sector_signal = getattr(agent.model.current_policy_signal, agent.sector_name)
        acceleration_window = int((sector_signal.adoption_mandate + clean_fuel_subsidy) * 5)
        due_rows = agent.fleet.due_replacement_indices(
            year,
            acceleration_window=acceleration_window,
        )
        planned_rows = agent.fleet.planned_investment_row_indices(year)
        if not planned_rows:
            return due_rows
        combined_rows = list(due_rows)
        for row_index in planned_rows:
            if row_index not in combined_rows:
                combined_rows.append(row_index)
        return combined_rows

    def _replace_due_assets(
        self,
        agent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        rows_to_replace = (
            self.replacement_row_indices(agent, year)
            if replacement_rows is None
            else replacement_rows
        )
        planned_rows = set(agent.fleet.planned_investment_row_indices(year))
        for row_index in rows_to_replace:
            asset = agent.fleet.frame.loc[row_index]
            technology_row, evaluation, action = self._select_technology_for_asset(
                agent,
                asset,
                year,
                initial_ets_balance=agent.remaining_ets_allowance,
                row_index=row_index,
            )
            if action == "continue_current":
                self._continue_operation(agent, row_index, evaluation, year)
                continue
            if row_index in planned_rows:
                action = "planned_investment"
            self._apply_technology(
                agent,
                row_index,
                technology_row,
                evaluation,
                year,
                action=action,
            )

    def _select_technology_for_asset(
        self,
        agent,
        asset: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        is_planned = row_index is not None and not agent.fleet.planned_technology_choices(
            row_index,
            year,
        ).empty
        candidates = (
            agent.fleet.planned_technology_choices(row_index, year)
            if is_planned
            else agent.candidate_technology_rows(asset)
        )

        evaluations: list[tuple[pd.Series, CandidateEvaluation, str]] = []
        for _, technology_row in candidates.iterrows():
            if not self.is_candidate_available(
                agent,
                technology_row,
                year,
                str(asset["segment"]),
            ):
                continue
            evaluation = self.calc_payback_year(
                agent,
                asset,
                technology_row,
                year,
                initial_ets_balance,
            )
            evaluations.append((technology_row, evaluation, "invest"))

        if (
            not is_planned
            and row_index is not None
            and agent.model.scenario.investment_timing.include_continue_option
            and int(asset["replacement_year"]) - year > 0
        ):
            current_row = agent.technology_row(
                technology_name=str(asset["current_technology"]),
            )
            continue_evaluation = self.evaluate_continue_current(
                agent,
                asset,
                year,
                initial_ets_balance,
            )
            evaluations.append((current_row, continue_evaluation, "continue_current"))

        if not evaluations:
            current_row = agent.technology_row(
                technology_name=str(asset["current_technology"]),
            )
            return (
                current_row,
                self.calc_payback_year(
                    agent,
                    asset,
                    current_row,
                    year,
                    initial_ets_balance,
                ),
                "invest",
            )

        evaluations.sort(key=lambda item: item[1].total_utility, reverse=True)
        return evaluations[0]

    def _add_growth_assets(self, agent, year: int) -> None:
        next_asset_id = agent.fleet.next_aircraft_id()
        for segment in sorted(agent.fleet.frame["segment"].dropna().unique()):
            template = agent.segment_template(str(segment))
            if template is None:
                continue

            residual_demand_gap = max(
                self._allocated_demand(agent, str(segment), year)
                - self._segment_capacity(agent, str(segment), year),
                0.0,
            )
            if residual_demand_gap <= 0.0:
                continue

            planned_rows = agent.planned_delivery_rows(str(segment), year)
            if not planned_rows.empty:
                planned_rows = planned_rows.assign(
                    _technology_specific=planned_rows["technology_name"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .ne(""),
                ).sort_values(
                    by=["_technology_specific", "technology_name"],
                    ascending=[False, True],
                    kind="stable",
                )

            for _, planned_delivery in planned_rows.iterrows():
                delivery_count = max(int(round(float(planned_delivery["value"]))), 0)
                if delivery_count == 0:
                    continue

                forced_technology_name = clean_scope_value(
                    planned_delivery.get("technology_name", ""),
                )
                for _ in range(delivery_count):
                    technology_row, evaluation = self._growth_addition_choice(
                        agent,
                        template,
                        year,
                        forced_technology_name=forced_technology_name or None,
                    )
                    new_row_index = agent.fleet.add_aircraft_from_template(
                        template,
                        next_aircraft_id=next_asset_id,
                    )
                    self._apply_technology(agent, new_row_index, technology_row, evaluation, year)
                    added_capacity = self._asset_capacity(
                        agent,
                        agent.fleet.frame.loc[new_row_index],
                        technology_row,
                        year,
                    )
                    residual_demand_gap = max(residual_demand_gap - added_capacity, 0.0)
                    next_asset_id += 1
                    if residual_demand_gap <= 0.0:
                        break
                if residual_demand_gap <= 0.0:
                    break

            if residual_demand_gap <= 0.0:
                continue

            segment_rows = agent.fleet.frame.loc[agent.fleet.frame["segment"] == segment]
            max_endogenous_additions = max(len(segment_rows) * 4, 10)
            additions_made = 0
            while residual_demand_gap > 0.0 and additions_made < max_endogenous_additions:
                technology_row, evaluation = self._growth_addition_choice(agent, template, year)
                new_row_index = agent.fleet.add_aircraft_from_template(
                    template,
                    next_aircraft_id=next_asset_id,
                )
                self._apply_technology(agent, new_row_index, technology_row, evaluation, year)
                added_capacity = self._asset_capacity(
                    agent,
                    agent.fleet.frame.loc[new_row_index],
                    technology_row,
                    year,
                )
                if added_capacity <= 0.0:
                    break
                residual_demand_gap = max(residual_demand_gap - added_capacity, 0.0)
                next_asset_id += 1
                additions_made += 1

    def _growth_addition_choice(
        self,
        agent,
        template: pd.Series,
        year: int,
        *,
        forced_technology_name: str | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation]:
        if forced_technology_name:
            technology_row = agent.technology_row(technology_name=forced_technology_name)
            evaluation = self.calc_payback_year(
                agent,
                template,
                technology_row,
                year,
                initial_ets_balance=agent.remaining_ets_allowance,
            )
            return technology_row, evaluation

        technology_row, evaluation, _action = self._select_technology_for_asset(
            agent,
            template,
            year,
            initial_ets_balance=agent.remaining_ets_allowance,
        )
        return technology_row, evaluation

    def calc_payback_year(
        self,
        agent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> CandidateEvaluation:
        life_time = max(int(technology_row["lifetime_years"]), 1)
        dynamic_price_index = agent.scenario_value(
            "technology_dynamic_price_index",
            year,
            segment=clean_scope_value(asset["segment"]),
            technology_name=clean_scope_value(technology_row["technology_name"]),
            default=0.0,
        )
        asset_price = float(technology_row["capex_eur"]) * (1.0 + float(dynamic_price_index))
        depreciation_cost = float(technology_row["depreciation_cost_share"]) * asset_price
        interest_rate = float(technology_row["payback_interest_rate"])

        # By default (residual_value_method="none"), cash flows are projected over the
        # technology's full nominal lifetime regardless of the model horizon, matching
        # today's behavior exactly. Opting into straight_line_remaining_life truncates
        # the projection at the horizon and credits back the unused CAPEX life instead of
        # the full-lifetime salvage value.
        residual_value_method = agent.model.scenario.investment_timing.residual_value_method
        horizon_periods = max(agent.model.scenario.end_year - year + 1, 0)
        if residual_value_method == "straight_line_remaining_life" and horizon_periods < life_time:
            evaluated_periods = horizon_periods
            residual_value = asset_price * (life_time - evaluated_periods) / life_time
        else:
            evaluated_periods = life_time
            residual_value = max(asset_price - (depreciation_cost * life_time), 0.0)

        total_costs: list[float] = []
        revenues: list[float] = []
        first_year_metrics: OperationMetrics | None = None
        for offset in range(evaluated_periods):
            future_year = min(year + offset, agent.model.scenario.end_year)
            operation_metrics = self.annual_operation_metrics(
                agent,
                asset,
                technology_row,
                future_year,
                initial_ets_balance if offset == 0 else None,
            )
            if offset == 0:
                first_year_metrics = operation_metrics
            revenue = self._compute_revenue(agent, asset, technology_row, future_year)
            additional_costs = self._additional_operating_costs(revenue, technology_row)
            total_costs.append(operation_metrics.total_cost + additional_costs + depreciation_cost)
            revenues.append(revenue)

        npv = -asset_price
        payback_year = life_time
        max_npv = float("-inf")
        max_npv_year = life_time - 1
        broke_early = False
        for offset, (revenue, cost) in enumerate(zip(revenues, total_costs, strict=False), start=1):
            npv += (revenue - cost) / ((1.0 + interest_rate) ** offset)
            if npv > max_npv:
                max_npv = npv
                max_npv_year = offset - 1
            if npv > 0:
                payback_year = offset - 1
                broke_early = True
                break
        if not broke_early:
            payback_year = self._payback_year_fallback(life_time, max_npv_year)
        npv += residual_value / ((1.0 + interest_rate) ** evaluated_periods)

        economic_utility = clamp(((life_time + 1) - payback_year) / max(life_time, 1), 0.0, 1.0)
        environmental_utility = self.environmental_utility(technology_row)
        technology_name = str(technology_row["technology_name"])
        if first_year_metrics is None:
            first_year_metrics = self.annual_operation_metrics(
                agent,
                asset,
                technology_row,
                year,
                initial_ets_balance,
            )
        policy_bonus = 0.0
        if not agent.technology_catalog.is_conventional_row(technology_row):
            sector_signal = getattr(agent.model.current_policy_signal, agent.sector_name)
            policy_bonus = (
                0.08 * self.current_clean_fuel_subsidy(agent)
                + 0.06 * sector_signal.adoption_mandate
            )

        total_utility = (
            economic_utility * agent.operator_economic_weight
            + environmental_utility * agent.operator_environmental_weight
            + policy_bonus
        )
        mean_total_cost = sum(total_costs) / max(len(total_costs), 1)
        mean_operation_cost = sum(
            revenue - (revenue - cost + depreciation_cost)
            for revenue, cost in zip(revenues, total_costs, strict=False)
        ) / max(len(total_costs), 1)
        return CandidateEvaluation(
            technology_name=technology_name,
            total_utility=total_utility,
            economic_utility=economic_utility,
            environmental_utility=environmental_utility,
            payback_year=payback_year,
            total_emission=first_year_metrics.total_emission,
            primary_energy_quantity=first_year_metrics.primary_energy_quantity,
            secondary_energy_quantity=first_year_metrics.secondary_energy_quantity,
            chargeable_emission=first_year_metrics.chargeable_emission,
            remaining_ets_allowance=first_year_metrics.remaining_ets_allowance,
            current_year_operating_cost=first_year_metrics.total_cost,
            effective_conventional_cost=mean_total_cost,
            effective_alternative_cost=mean_operation_cost,
            net_present_value=npv,
        )

    def evaluate_continue_current(
        self,
        agent,
        asset: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> CandidateEvaluation:
        """Evaluate keeping the asset on its current technology, at zero capex.

        Mirrors `calc_payback_year` but with no fresh investment: the asset is
        assumed sunk, so there is no depreciation/salvage schedule to restart, and
        the projection only covers the asset's already-scheduled remaining
        lifetime (`replacement_year - year`) rather than a fresh full lifetime.
        """
        technology_row = agent.technology_row(str(asset["current_technology"]))
        remaining_lifetime = max(int(asset["replacement_year"]) - year, 0)
        residual_value_method = agent.model.scenario.investment_timing.residual_value_method
        if residual_value_method == "straight_line_remaining_life":
            horizon_periods = max(agent.model.scenario.end_year - year + 1, 0)
            evaluated_periods = min(remaining_lifetime, horizon_periods)
        else:
            evaluated_periods = remaining_lifetime

        total_costs: list[float] = []
        revenues: list[float] = []
        first_year_metrics: OperationMetrics | None = None
        for offset in range(evaluated_periods):
            future_year = min(year + offset, agent.model.scenario.end_year)
            operation_metrics = self.annual_operation_metrics(
                agent,
                asset,
                technology_row,
                future_year,
                initial_ets_balance if offset == 0 else None,
            )
            if offset == 0:
                first_year_metrics = operation_metrics
            revenue = self._compute_revenue(agent, asset, technology_row, future_year)
            additional_costs = self._additional_operating_costs(revenue, technology_row)
            total_costs.append(operation_metrics.total_cost + additional_costs)
            revenues.append(revenue)

        interest_rate = float(technology_row["payback_interest_rate"])
        npv = 0.0
        for offset, (revenue, cost) in enumerate(zip(revenues, total_costs, strict=False), start=1):
            npv += (revenue - cost) / ((1.0 + interest_rate) ** offset)

        # No capex was spent, so there is no capital to pay back: continuing is
        # always scored as maximally payback-efficient on the economic axis. Whether
        # continuing is actually cash-flow positive still shows up in `net_present_value`,
        # which the ambiguity-aware NPV-based selection uses directly.
        economic_utility = 1.0
        environmental_utility = self.environmental_utility(technology_row)
        technology_name = str(technology_row["technology_name"])
        if first_year_metrics is None:
            first_year_metrics = self.annual_operation_metrics(
                agent,
                asset,
                technology_row,
                year,
                initial_ets_balance,
            )
        policy_bonus = 0.0
        if not agent.technology_catalog.is_conventional_row(technology_row):
            sector_signal = getattr(agent.model.current_policy_signal, agent.sector_name)
            policy_bonus = (
                0.08 * self.current_clean_fuel_subsidy(agent)
                + 0.06 * sector_signal.adoption_mandate
            )
        total_utility = (
            economic_utility * agent.operator_economic_weight
            + environmental_utility * agent.operator_environmental_weight
            + policy_bonus
        )
        mean_total_cost = sum(total_costs) / max(len(total_costs), 1)
        mean_operation_cost = sum(
            revenue - (revenue - cost) for revenue, cost in zip(revenues, total_costs, strict=False)
        ) / max(len(total_costs), 1)
        return CandidateEvaluation(
            technology_name=technology_name,
            total_utility=total_utility,
            economic_utility=economic_utility,
            environmental_utility=environmental_utility,
            payback_year=0,
            total_emission=first_year_metrics.total_emission,
            primary_energy_quantity=first_year_metrics.primary_energy_quantity,
            secondary_energy_quantity=first_year_metrics.secondary_energy_quantity,
            chargeable_emission=first_year_metrics.chargeable_emission,
            remaining_ets_allowance=first_year_metrics.remaining_ets_allowance,
            current_year_operating_cost=first_year_metrics.total_cost,
            effective_conventional_cost=mean_total_cost,
            effective_alternative_cost=mean_operation_cost,
            net_present_value=npv,
        )

    def _payback_year_fallback(self, life_time: int, max_npv_year: int) -> int:
        """Payback year to use when NPV never turns positive within the horizon.

        The default (used by every sector except maritime passenger) is the
        conservative `life_time` (worst case: never pays back). Overridden by
        `LegacyWeightedUtilityMaritimePassengerLogic` to use the best-NPV year
        seen instead, matching that sector's existing, deliberately different
        formula exactly.
        """
        del max_npv_year
        return life_time
