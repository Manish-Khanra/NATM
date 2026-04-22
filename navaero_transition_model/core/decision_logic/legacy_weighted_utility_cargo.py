from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from navaero_transition_model.core.decision_logic.base import (
    AviationCargoDecisionLogic,
    CandidateEvaluation,
    OperationMetrics,
    clamp,
    clean_scope_value,
)

if TYPE_CHECKING:
    from navaero_transition_model.core.agent_types.aviation_cargo_airline import (
        AviationCargoAirlineAgent,
    )


class LegacyWeightedUtilityCargoLogic(AviationCargoDecisionLogic):
    name = "legacy_weighted_utility_cargo"

    def step(self, agent: AviationCargoAirlineAgent, year: int) -> None:
        replacement_rows = self.replacement_row_indices(agent, year)
        agent.update_existing_fleet(year, excluded_indices=set(replacement_rows))
        self._replace_due_aircraft(agent, year, replacement_rows=replacement_rows)
        self._add_growth_aircraft(agent, year)

    def current_carbon_price(self, agent: AviationCargoAirlineAgent, year: int) -> float:
        scenario_price = agent.scenario_value("carbon_price", year)
        if scenario_price is None:
            return float(agent.model.current_policy_signal.carbon_price)
        return max(float(scenario_price), float(agent.model.current_policy_signal.carbon_price))

    def current_mandate_share(
        self,
        agent: AviationCargoAirlineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        secondary_carrier = clean_scope_value(technology_row.get("secondary_energy_carrier", ""))
        saf_pathway = clean_scope_value(technology_row.get("saf_pathway", ""))
        scenario_value = agent.scenario_value(
            "saf_mandate",
            year,
            secondary_energy_carrier=secondary_carrier,
            saf_pathway=saf_pathway,
        )
        policy_mandate = float(agent.model.current_policy_signal.aviation.adoption_mandate)
        if scenario_value is None:
            return policy_mandate
        return clamp(max(float(scenario_value), policy_mandate))

    def current_clean_fuel_subsidy(self, agent: AviationCargoAirlineAgent) -> float:
        return float(agent.model.current_policy_signal.aviation.clean_fuel_subsidy)

    def effective_secondary_share(
        self,
        agent: AviationCargoAirlineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        segment = clean_scope_value(technology_row["segment"])
        technology_name = clean_scope_value(technology_row["technology_name"])
        secondary_carrier = clean_scope_value(technology_row.get("secondary_energy_carrier", ""))
        saf_pathway = clean_scope_value(technology_row.get("saf_pathway", ""))
        max_share = float(technology_row["maximum_secondary_energy_share"])
        scenario_cap = agent.scenario_value(
            "maximum_secondary_energy_share",
            year,
            country=agent.operator_country,
            segment=segment,
            technology_name=technology_name,
            secondary_energy_carrier=secondary_carrier,
            saf_pathway=saf_pathway,
        )
        if scenario_cap is not None:
            max_share = clamp(float(scenario_cap))
        cap_active = agent.scenario_value(
            "secondary_energy_cap_active",
            year,
            country=agent.operator_country,
            segment=segment,
            technology_name=technology_name,
            secondary_energy_carrier=secondary_carrier,
            saf_pathway=saf_pathway,
            default=1.0 if max_share > 0.0 else 0.0,
        )
        if not bool(cap_active):
            return 0.0
        if max_share <= 0:
            return 0.0
        if int(technology_row["drop_in_fuel"]) == 1:
            mandate_active = agent.scenario_value(
                "drop_in_mandate_active",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
                default=1.0,
            )
            if not bool(mandate_active):
                return 0.0
            return min(max_share, self.current_mandate_share(agent, technology_row, year))
        return max_share

    def annual_operation_metrics(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics:
        trip_length = float(technology_row["trip_length_km"])
        trip_days = float(technology_row["trip_days_per_year"])
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        total_distance = trip_length * trip_days
        total_energy = total_distance / kilometer_per_kwh

        secondary_share = self.effective_secondary_share(agent, technology_row, year)
        primary_energy_quantity = total_energy * (1.0 - secondary_share)
        secondary_energy_quantity = total_energy * secondary_share

        primary_price = agent.scenario_value(
            "primary_energy_price",
            year,
            country=agent.operator_country,
            primary_energy_carrier=clean_scope_value(technology_row["primary_energy_carrier"]),
            default=0.0,
        )
        secondary_price = agent.scenario_value(
            "secondary_energy_price",
            year,
            country=agent.operator_country,
            secondary_energy_carrier=clean_scope_value(technology_row["secondary_energy_carrier"]),
            saf_pathway=clean_scope_value(technology_row["saf_pathway"]),
            default=0.0,
        )
        carbon_price = self.current_carbon_price(agent, year)
        clean_fuel_subsidy = self.current_clean_fuel_subsidy(agent)
        is_alternative = not agent.technology_catalog.is_conventional_row(technology_row)
        if is_alternative and secondary_energy_quantity > 0.0:
            secondary_price = float(secondary_price) * (1.0 - clean_fuel_subsidy)
        elif is_alternative:
            primary_price = float(primary_price) * (1.0 - clean_fuel_subsidy)

        primary_emission = primary_energy_quantity * float(
            technology_row["primary_energy_emission_factor"],
        )
        secondary_emission = secondary_energy_quantity * float(
            technology_row["secondary_energy_emission_factor"]
        )
        total_emission = primary_emission + secondary_emission

        if free_ets_balance is None:
            remaining_ets_allowance = self.yearly_ets_allowance(agent, year)
        else:
            remaining_ets_allowance = max(float(free_ets_balance), 0.0)
        covered_emission = min(remaining_ets_allowance, total_emission)
        chargeable_emission = max(total_emission - covered_emission, 0.0)
        remaining_ets_allowance = max(remaining_ets_allowance - total_emission, 0.0)
        energy_cost = primary_energy_quantity * float(
            primary_price
        ) + secondary_energy_quantity * float(secondary_price)
        emission_cost = chargeable_emission * carbon_price
        return OperationMetrics(
            total_cost=energy_cost + emission_cost,
            total_emission=total_emission,
            primary_energy_quantity=primary_energy_quantity,
            secondary_energy_quantity=secondary_energy_quantity,
            chargeable_emission=chargeable_emission,
            remaining_ets_allowance=remaining_ets_allowance,
        )

    def yearly_ets_allowance(self, agent: AviationCargoAirlineAgent, year: int) -> float:
        allocation_factor = agent.scenario_value(
            "ets_allocation_factor",
            year,
            operator_name=agent.operator_name,
            default=1.0,
        )
        return agent.free_ets_allocation * max(1.0 - float(allocation_factor), 0.0)

    def annual_revenue(
        self,
        agent: AviationCargoAirlineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        trip_length = float(technology_row["trip_length_km"])
        trip_days = float(technology_row["trip_days_per_year"])
        load_factor = agent.scenario_value(
            "load_factor",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        freight_rate = agent.scenario_value(
            "freight_rate",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        payload_capacity_tonnes = (
            float(technology_row.get("payload_capacity_kg", 0.0) or 0.0) / 1000.0
        )
        return (
            payload_capacity_tonnes
            * float(load_factor or 0.0)
            * trip_length
            * trip_days
            * float(freight_rate or 0.0)
        )

    def calc_payback_year(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> CandidateEvaluation:
        life_time = max(int(technology_row["lifetime_years"]), 1)
        dynamic_price_index = agent.scenario_value(
            "technology_dynamic_price_index",
            year,
            segment=clean_scope_value(technology_row["segment"]),
            technology_name=clean_scope_value(technology_row["technology_name"]),
            default=0.0,
        )
        aircraft_price = float(technology_row["capex_eur"]) * (1.0 + float(dynamic_price_index))
        depreciation_cost = float(technology_row["depreciation_cost_share"]) * aircraft_price
        salvage_value = (aircraft_price - (aircraft_price * depreciation_cost)) / life_time
        interest_rate = float(technology_row["payback_interest_rate"])

        total_costs: list[float] = []
        revenues: list[float] = []
        emissions: list[float] = []
        primary_energy_quantities: list[float] = []
        secondary_energy_quantities: list[float] = []
        first_year_metrics: OperationMetrics | None = None
        for offset in range(life_time):
            future_year = min(year + offset, agent.model.scenario.end_year)
            operation_metrics = self.annual_operation_metrics(
                agent,
                aircraft,
                technology_row,
                future_year,
                initial_ets_balance if offset == 0 else None,
            )
            if offset == 0:
                first_year_metrics = operation_metrics
            revenue = self.annual_revenue(agent, technology_row, future_year)
            maintenance_cost = revenue * float(technology_row["maintenance_cost_share"])
            wages = revenue * 0.24
            landing_fees = revenue * 0.10
            total_costs.append(
                operation_metrics.total_cost
                + maintenance_cost
                + wages
                + landing_fees
                + depreciation_cost,
            )
            revenues.append(revenue)
            emissions.append(operation_metrics.total_emission)
            primary_energy_quantities.append(operation_metrics.primary_energy_quantity)
            secondary_energy_quantities.append(operation_metrics.secondary_energy_quantity)

        npv = -aircraft_price
        payback_year = life_time
        for offset, (revenue, cost) in enumerate(zip(revenues, total_costs, strict=False), start=1):
            npv += (revenue - cost) / ((1.0 + interest_rate) ** offset)
            if npv > 0:
                payback_year = offset - 1
                break
        npv += salvage_value / ((1.0 + interest_rate) ** life_time)

        economic_utility = clamp(((life_time + 1) - payback_year) / max(life_time, 1), 0.0, 1.0)
        environmental_utility = self.environmental_utility(technology_row)
        technology_name = str(technology_row["technology_name"])
        if first_year_metrics is None:
            first_year_metrics = self.annual_operation_metrics(
                agent,
                aircraft,
                technology_row,
                year,
                initial_ets_balance,
            )
        policy_bonus = 0.0
        if not agent.technology_catalog.is_conventional(
            technology_name,
            str(technology_row["segment"]),
        ):
            policy_bonus = (
                0.08 * self.current_clean_fuel_subsidy(agent)
                + 0.06 * agent.model.current_policy_signal.aviation.adoption_mandate
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
        )

    def partial_environmental_utility(self, value: float, thresholds: tuple[float, ...]) -> float:
        if value <= 0.0:
            return 1.0
        if value <= thresholds[0]:
            return 0.9
        if value <= thresholds[1]:
            return 0.6
        if value <= thresholds[2]:
            return 0.4
        if value <= thresholds[3]:
            return 0.2
        return 0.0

    def environmental_utility(self, technology_row: pd.Series) -> float:
        hc = self.partial_environmental_utility(
            float(technology_row["hydrocarbon_factor"]),
            (148, 296, 444, 592),
        )
        co = self.partial_environmental_utility(
            float(technology_row["carbon_monoxide_factor"]),
            (131.8, 263.6, 395.4, 527.2),
        )
        nox = self.partial_environmental_utility(
            float(technology_row["nitrogen_oxide_factor"]),
            (16.78, 33.56, 50.34, 67.12),
        )
        smoke = self.partial_environmental_utility(
            float(technology_row["smoke_number_factor"]),
            (15.6, 31.2, 46.8, 62.4),
        )
        co2_primary = 1.0 if float(technology_row["primary_energy_emission_factor"]) == 0.0 else 0.0
        co2_secondary = (
            1.0 if float(technology_row["secondary_energy_emission_factor"]) == 0.0 else 0.0
        )
        return (
            0.10 * hc + 0.10 * co + 0.10 * nox + 0.10 * smoke + 0.30 * (co2_primary + co2_secondary)
        )

    def is_candidate_available(
        self,
        agent: AviationCargoAirlineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> bool:
        technology_name = clean_scope_value(technology_row["technology_name"])
        segment = clean_scope_value(technology_row["segment"])
        service_entry_year = technology_row.get("service_entry_year")
        if pd.notna(service_entry_year) and str(service_entry_year).strip() != "":
            if year < int(float(service_entry_year)):
                return False
        technology_flag = agent.scenario_value(
            "technology_availability",
            year,
            segment=segment,
            technology_name=technology_name,
            default=1.0,
        )
        infrastructure_flag = agent.scenario_value(
            "infrastructure_availability",
            year,
            country=agent.operator_country,
            segment=segment,
            technology_name=technology_name,
            default=1.0,
        )
        saf_pathway = clean_scope_value(technology_row["saf_pathway"])
        secondary_energy_carrier = clean_scope_value(technology_row["secondary_energy_carrier"])
        saf_flag = 1.0
        if secondary_energy_carrier not in {"", "none"}:
            saf_flag = agent.scenario_value(
                "saf_availability",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_energy_carrier,
                saf_pathway=saf_pathway,
                default=1.0,
            )
        return bool(technology_flag) and bool(infrastructure_flag) and bool(saf_flag)

    def select_technology_for_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation]:
        candidates = agent.technology_catalog.candidates_for_segment(str(aircraft["segment"]))
        evaluations: list[tuple[pd.Series, CandidateEvaluation]] = []
        for _, technology_row in candidates.iterrows():
            if not self.is_candidate_available(agent, technology_row, year):
                continue
            evaluation = self.calc_payback_year(
                agent,
                aircraft,
                technology_row,
                year,
                initial_ets_balance,
            )
            evaluations.append((technology_row, evaluation))

        if not evaluations:
            current_row = agent.technology_row(
                technology_name=str(aircraft["current_technology"]),
                segment=str(aircraft["segment"]),
            )
            return current_row, self.calc_payback_year(
                agent,
                aircraft,
                current_row,
                year,
                initial_ets_balance,
            )

        evaluations.sort(key=lambda item: item[1].total_utility, reverse=True)
        return evaluations[0]

    def replacement_row_indices(self, agent: AviationCargoAirlineAgent, year: int) -> list[int]:
        clean_fuel_subsidy = self.current_clean_fuel_subsidy(agent)
        acceleration_window = int(
            (agent.model.current_policy_signal.aviation.adoption_mandate + clean_fuel_subsidy) * 5,
        )
        return agent.fleet.due_replacement_indices(
            year,
            acceleration_window=acceleration_window,
        )

    def replace_due_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        rows_to_replace = (
            self.replacement_row_indices(agent, year)
            if replacement_rows is None
            else replacement_rows
        )
        for row_index in rows_to_replace:
            aircraft = agent.fleet.frame.loc[row_index]
            technology_row, evaluation = self.select_technology_for_aircraft(
                agent,
                aircraft,
                year,
                initial_ets_balance=agent.remaining_ets_allowance,
            )
            agent.apply_technology_to_aircraft(row_index, technology_row, evaluation, year)

    def add_growth_aircraft(self, agent: AviationCargoAirlineAgent, year: int) -> None:
        next_aircraft_id = agent.fleet.next_aircraft_id()
        for segment in sorted(agent.fleet.frame["segment"].dropna().unique()):
            template = agent.segment_template(str(segment))
            if template is None:
                continue

            residual_tonne_km_gap = max(
                agent.allocated_freight_tonne_km(str(segment), year)
                - agent.segment_freight_tonne_km_capacity(str(segment), year),
                0.0,
            )
            if residual_tonne_km_gap <= 0.0:
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
                        next_aircraft_id=next_aircraft_id,
                    )
                    agent.apply_technology_to_aircraft(
                        new_row_index,
                        technology_row,
                        evaluation,
                        year,
                    )
                    added_capacity = agent.aircraft_freight_tonne_km_capacity(
                        agent.fleet.frame.loc[new_row_index],
                        technology_row,
                        year,
                    )
                    residual_tonne_km_gap = max(residual_tonne_km_gap - added_capacity, 0.0)
                    next_aircraft_id += 1
                    if residual_tonne_km_gap <= 0.0:
                        break
                if residual_tonne_km_gap <= 0.0:
                    break

            if residual_tonne_km_gap <= 0.0:
                continue

            segment_rows = agent.fleet.frame.loc[agent.fleet.frame["segment"] == segment]
            max_endogenous_additions = max(len(segment_rows) * 4, 10)
            additions_made = 0
            while residual_tonne_km_gap > 0.0 and additions_made < max_endogenous_additions:
                technology_row, evaluation = self._growth_addition_choice(
                    agent,
                    template,
                    year,
                )
                new_row_index = agent.fleet.add_aircraft_from_template(
                    template,
                    next_aircraft_id=next_aircraft_id,
                )
                agent.apply_technology_to_aircraft(
                    new_row_index,
                    technology_row,
                    evaluation,
                    year,
                )
                added_capacity = agent.aircraft_freight_tonne_km_capacity(
                    agent.fleet.frame.loc[new_row_index],
                    technology_row,
                    year,
                )
                if added_capacity <= 0.0:
                    break
                residual_tonne_km_gap = max(residual_tonne_km_gap - added_capacity, 0.0)
                next_aircraft_id += 1
                additions_made += 1

    def _growth_addition_choice(
        self,
        agent: AviationCargoAirlineAgent,
        template: pd.Series,
        year: int,
        *,
        forced_technology_name: str | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation]:
        if forced_technology_name:
            technology_row = agent.technology_row(
                technology_name=forced_technology_name,
                segment=str(template["segment"]),
            )
            evaluation = self.calc_payback_year(
                agent,
                template,
                technology_row,
                year,
                initial_ets_balance=agent.remaining_ets_allowance,
            )
            return technology_row, evaluation

        return self.select_technology_for_aircraft(
            agent,
            template,
            year,
            initial_ets_balance=agent.remaining_ets_allowance,
        )

    def _replace_due_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        self.replace_due_aircraft(agent, year, replacement_rows=replacement_rows)

    def _add_growth_aircraft(self, agent: AviationCargoAirlineAgent, year: int) -> None:
        self.add_growth_aircraft(agent, year)
