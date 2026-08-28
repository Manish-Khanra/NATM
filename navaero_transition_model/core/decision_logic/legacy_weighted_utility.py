from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from navaero_transition_model.core.decision_logic.base import (
    AviationCargoDecisionLogic,
    AviationPassengerDecisionLogic,
    CandidateEvaluation,
    MaritimeCargoDecisionLogic,
    MaritimePassengerDecisionLogic,
    OperationMetrics,
    clamp,
    clean_scope_value,
)
from navaero_transition_model.core.decision_logic.scorer import NATMDecisionScorer

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


AVERAGE_PASSENGER_WEIGHT_KG = 100.0


class LegacyWeightedUtilityLogic(NATMDecisionScorer, AviationPassengerDecisionLogic):
    name = "legacy_weighted_utility"

    def current_carbon_price(self, agent: AviationPassengerAirlineAgent, year: int) -> float:
        scenario_price = agent.scenario_value("carbon_price", year)
        if scenario_price is None:
            return float(agent.model.current_policy_signal.carbon_price)
        return max(float(scenario_price), float(agent.model.current_policy_signal.carbon_price))

    def current_mandate_share(
        self,
        agent: AviationPassengerAirlineAgent,
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

    def current_clean_fuel_subsidy(self, agent: AviationPassengerAirlineAgent) -> float:
        return float(agent.model.current_policy_signal.aviation.clean_fuel_subsidy)

    def effective_secondary_share(
        self,
        agent: AviationPassengerAirlineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        segment = clean_scope_value(operation_segment)
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
        agent: AviationPassengerAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics:
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        total_distance = agent.fleet.annual_distance_km_for(aircraft, technology_row)
        total_energy = total_distance / kilometer_per_kwh

        operation_segment = clean_scope_value(aircraft["segment"])
        secondary_share = self.effective_secondary_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )
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

    def yearly_ets_allowance(self, agent: AviationPassengerAirlineAgent, year: int) -> float:
        allocation_factor = agent.scenario_value(
            "ets_allocation_factor",
            year,
            operator_name=agent.operator_name,
            default=1.0,
        )
        return agent.free_ets_allocation * max(1.0 - float(allocation_factor), 0.0)

    def annual_revenue(
        self,
        agent: AviationPassengerAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        annual_distance = agent.fleet.annual_distance_km_for(aircraft, technology_row)
        annual_flights = agent.fleet.annual_flights_for(aircraft, technology_row)
        economy_occupancy = agent.scenario_value(
            "economy_occupancy",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        business_occupancy = agent.scenario_value(
            "business_occupancy",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        first_occupancy = agent.scenario_value(
            "first_occupancy",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        economy_income = agent.scenario_value(
            "economy_income",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        business_income = agent.scenario_value(
            "business_income",
            year,
            operator_name=agent.operator_name,
            default=0.0,
        )
        first_income = agent.scenario_value(
            "first_income",
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

        economy_revenue = (
            float(technology_row["economy_seats"])
            * float(economy_occupancy)
            * annual_distance
            * float(economy_income)
            / 100.0
        )
        business_revenue = (
            float(technology_row["business_seats"])
            * float(business_occupancy)
            * annual_distance
            * float(business_income)
            / 100.0
        )
        first_revenue = (
            float(technology_row["first_class_seats"])
            * float(first_occupancy)
            * annual_distance
            * float(first_income)
            / 100.0
        )

        passenger_mass = (
            float(technology_row["economy_seats"]) * float(economy_occupancy)
            + float(technology_row["business_seats"]) * float(business_occupancy)
            + float(technology_row["first_class_seats"]) * float(first_occupancy)
        ) * AVERAGE_PASSENGER_WEIGHT_KG
        spare_cargo_mass = max(
            float(technology_row["mtow"]) - float(technology_row["oew"]) - passenger_mass,
            0.0,
        )
        cargo_revenue = (spare_cargo_mass / 1000.0) * float(freight_rate) * annual_flights
        return economy_revenue + business_revenue + first_revenue + cargo_revenue

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
        # Thresholds are real-EDB-calibrated: base = max(real conventional
        # aircraft's ICAO/EASA-certified value across the installed fleet) / 4,
        # same linear-quartile structure as the original (arbitrary) constants
        # they replace. See data/archive/registration_matching/
        # fix_aviation_emission_factors.py for the derivation.
        hc = self.partial_environmental_utility(
            float(technology_row["hydrocarbon_factor"]),
            (1.45, 2.89, 4.33, 5.78),
        )
        co = self.partial_environmental_utility(
            float(technology_row["carbon_monoxide_factor"]),
            (11.72, 23.44, 35.16, 46.88),
        )
        nox = self.partial_environmental_utility(
            float(technology_row["nitrogen_oxide_factor"]),
            (17.33, 34.66, 51.98, 69.31),
        )
        smoke = self.partial_environmental_utility(
            float(technology_row["smoke_number_factor"]),
            (2.51, 5.01, 7.52, 10.03),
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
        agent: AviationPassengerAirlineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> bool:
        technology_name = clean_scope_value(technology_row["technology_name"])
        segment = clean_scope_value(operation_segment)
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

    # --- NATMDecisionScorer hooks -------------------------------------------------

    def _compute_revenue(
        self,
        agent: AviationPassengerAirlineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return self.annual_revenue(agent, asset, technology_row, year)

    def _additional_operating_costs(self, revenue: float, technology_row: pd.Series) -> float:
        maintenance_cost = revenue * float(technology_row["maintenance_cost_share"])
        wages = revenue * 0.24
        landing_fees = revenue * 0.10
        return maintenance_cost + wages + landing_fees

    def _asset_capacity(
        self,
        agent: AviationPassengerAirlineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return agent.aircraft_passenger_km_capacity(asset, technology_row, year)

    def _segment_capacity(
        self,
        agent: AviationPassengerAirlineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.segment_passenger_km_capacity(segment, year)

    def _allocated_demand(
        self,
        agent: AviationPassengerAirlineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.allocated_passenger_km(segment, year)

    def _apply_technology(
        self,
        agent: AviationPassengerAirlineAgent,
        row_index: int,
        technology_row: pd.Series,
        evaluation: CandidateEvaluation,
        year: int,
        *,
        action: str = "invest",
    ) -> None:
        agent.apply_technology_to_aircraft(
            row_index,
            technology_row,
            evaluation,
            year,
            action=action,
        )

    def _continue_operation(
        self,
        agent: AviationPassengerAirlineAgent,
        row_index: int,
        evaluation: CandidateEvaluation,
        year: int,
    ) -> None:
        agent.continue_aircraft_operation(row_index, evaluation, year)

    # --- Public per-sector aliases (external API preserved exactly) --------------

    def select_technology_for_aircraft(
        self,
        agent: AviationPassengerAirlineAgent,
        aircraft: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        return self._select_technology_for_asset(
            agent,
            aircraft,
            year,
            initial_ets_balance,
            row_index=row_index,
        )

    def replace_due_aircraft(
        self,
        agent: AviationPassengerAirlineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        self._replace_due_assets(agent, year, replacement_rows=replacement_rows)

    def add_growth_aircraft(self, agent: AviationPassengerAirlineAgent, year: int) -> None:
        self._add_growth_assets(agent, year)


class LegacyWeightedUtilityCargoLogic(NATMDecisionScorer, AviationCargoDecisionLogic):
    name = LegacyWeightedUtilityLogic.name

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
        operation_segment: str,
    ) -> float:
        segment = clean_scope_value(operation_segment)
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
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        total_distance = agent.fleet.annual_distance_km_for(aircraft, technology_row)
        total_energy = total_distance / kilometer_per_kwh

        operation_segment = clean_scope_value(aircraft["segment"])
        secondary_share = self.effective_secondary_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )
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
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        annual_distance = agent.fleet.annual_distance_km_for(aircraft, technology_row)
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
            * annual_distance
            * float(freight_rate or 0.0)
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
        # Thresholds are real-EDB-calibrated: base = max(real conventional
        # aircraft's ICAO/EASA-certified value across the installed fleet) / 4,
        # same linear-quartile structure as the original (arbitrary) constants
        # they replace. See data/archive/registration_matching/
        # fix_aviation_emission_factors.py for the derivation.
        hc = self.partial_environmental_utility(
            float(technology_row["hydrocarbon_factor"]),
            (1.45, 2.89, 4.33, 5.78),
        )
        co = self.partial_environmental_utility(
            float(technology_row["carbon_monoxide_factor"]),
            (11.72, 23.44, 35.16, 46.88),
        )
        nox = self.partial_environmental_utility(
            float(technology_row["nitrogen_oxide_factor"]),
            (17.33, 34.66, 51.98, 69.31),
        )
        smoke = self.partial_environmental_utility(
            float(technology_row["smoke_number_factor"]),
            (2.51, 5.01, 7.52, 10.03),
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
        operation_segment: str,
    ) -> bool:
        technology_name = clean_scope_value(technology_row["technology_name"])
        segment = clean_scope_value(operation_segment)
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

    # --- NATMDecisionScorer hooks -------------------------------------------------

    def _compute_revenue(
        self,
        agent: AviationCargoAirlineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return self.annual_revenue(agent, asset, technology_row, year)

    def _additional_operating_costs(self, revenue: float, technology_row: pd.Series) -> float:
        maintenance_cost = revenue * float(technology_row["maintenance_cost_share"])
        wages = revenue * 0.24
        landing_fees = revenue * 0.10
        return maintenance_cost + wages + landing_fees

    def _asset_capacity(
        self,
        agent: AviationCargoAirlineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return agent.aircraft_freight_tonne_km_capacity(asset, technology_row, year)

    def _segment_capacity(self, agent: AviationCargoAirlineAgent, segment: str, year: int) -> float:
        return agent.segment_freight_tonne_km_capacity(segment, year)

    def _allocated_demand(self, agent: AviationCargoAirlineAgent, segment: str, year: int) -> float:
        return agent.allocated_freight_tonne_km(segment, year)

    def _apply_technology(
        self,
        agent: AviationCargoAirlineAgent,
        row_index: int,
        technology_row: pd.Series,
        evaluation: CandidateEvaluation,
        year: int,
        *,
        action: str = "invest",
    ) -> None:
        agent.apply_technology_to_aircraft(
            row_index,
            technology_row,
            evaluation,
            year,
            action=action,
        )

    def _continue_operation(
        self,
        agent: AviationCargoAirlineAgent,
        row_index: int,
        evaluation: CandidateEvaluation,
        year: int,
    ) -> None:
        agent.continue_aircraft_operation(row_index, evaluation, year)

    # --- Public per-sector aliases (external API preserved exactly) --------------

    def select_technology_for_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        return self._select_technology_for_asset(
            agent,
            aircraft,
            year,
            initial_ets_balance,
            row_index=row_index,
        )

    def replace_due_aircraft(
        self,
        agent: AviationCargoAirlineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        self._replace_due_assets(agent, year, replacement_rows=replacement_rows)

    def add_growth_aircraft(self, agent: AviationCargoAirlineAgent, year: int) -> None:
        self._add_growth_assets(agent, year)


class LegacyWeightedUtilityMaritimeCargoLogic(NATMDecisionScorer, MaritimeCargoDecisionLogic):
    name = LegacyWeightedUtilityLogic.name

    def current_carbon_price(self, agent: MaritimeCargoShiplineAgent, year: int) -> float:
        scenario_price = agent.scenario_value("carbon_tax", year)
        if scenario_price is None:
            scenario_price = agent.scenario_value("carbon_price", year)
        if scenario_price is None:
            return float(agent.model.current_policy_signal.carbon_price)
        return max(float(scenario_price), float(agent.model.current_policy_signal.carbon_price))

    def current_biofuel_mandate(
        self,
        agent: MaritimeCargoShiplineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        secondary_carrier = clean_scope_value(technology_row.get("secondary_energy_carrier", ""))
        saf_pathway = clean_scope_value(technology_row.get("saf_pathway", ""))
        scenario_value = agent.scenario_value(
            "biofuel_mandate",
            year,
            secondary_energy_carrier=secondary_carrier,
            saf_pathway=saf_pathway,
        )
        if scenario_value is None:
            scenario_value = agent.scenario_value(
                "adoption_mandate",
                year,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
            )
        policy_mandate = float(agent.model.current_policy_signal.maritime.adoption_mandate)
        if scenario_value is None:
            return policy_mandate
        return clamp(max(float(scenario_value), policy_mandate))

    def current_reported_emission_share(
        self,
        agent: MaritimeCargoShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        scenario_value = agent.scenario_value(
            "reported_emission",
            year,
            country=agent.operator_country,
            operator_name=agent.operator_name,
            segment=clean_scope_value(operation_segment),
            technology_name=clean_scope_value(technology_row["technology_name"]),
            default=None,
        )
        if scenario_value is None:
            scenario_value = technology_row.get("reported_emission_factor", 1.0)
        return max(float(scenario_value or 0.0), 0.0)

    def current_clean_fuel_subsidy(self, agent: MaritimeCargoShiplineAgent) -> float:
        return float(agent.model.current_policy_signal.maritime.clean_fuel_subsidy)

    def effective_secondary_share(
        self,
        agent: MaritimeCargoShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        segment = clean_scope_value(operation_segment)
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
        elif (
            legacy_cap := agent.scenario_value(
                "maximum_secondary_energy",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
                default=None,
            )
        ) is not None:
            max_share = clamp(float(legacy_cap))
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
        if cap_active is None:
            cap_active = agent.scenario_value(
                "maximum_cap_secondary_energy",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
                default=1.0 if max_share > 0.0 else 0.0,
            )
        if not bool(cap_active) or max_share <= 0.0:
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
            if mandate_active is None:
                mandate_active = agent.scenario_value(
                    "drop_in_fuel_mandate",
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
            return min(max_share, self.current_biofuel_mandate(agent, technology_row, year))
        return max_share

    def annual_operation_metrics(
        self,
        agent: MaritimeCargoShiplineAgent,
        vessel: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics:
        trip_length = float(technology_row["trip_length_km"])
        trip_days = float(technology_row["trip_days_per_year"])
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        total_distance = trip_length * trip_days
        total_energy = total_distance / kilometer_per_kwh

        operation_segment = clean_scope_value(vessel["segment"])
        secondary_share = self.effective_secondary_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )
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
        tertiary_price = agent.scenario_value(
            "tertiary_energy_price",
            year,
            country=agent.operator_country,
            secondary_energy_carrier=clean_scope_value(technology_row["secondary_energy_carrier"]),
            saf_pathway=clean_scope_value(technology_row["saf_pathway"]),
            default=None,
        )
        carbon_price = self.current_carbon_price(agent, year)
        clean_fuel_subsidy = self.current_clean_fuel_subsidy(agent)
        is_alternative = not agent.technology_catalog.is_conventional_row(technology_row)
        if int(technology_row["drop_in_fuel"]) == 1 and tertiary_price is not None:
            secondary_price = tertiary_price
        if is_alternative and secondary_energy_quantity > 0.0:
            secondary_price = float(secondary_price) * (1.0 - clean_fuel_subsidy)
        elif is_alternative:
            primary_price = float(primary_price) * (1.0 - clean_fuel_subsidy)

        carbondioxide_factor = float(technology_row.get("carbondioxide_factor", 0.0) or 0.0)
        if carbondioxide_factor > 0.0:
            total_emission = carbondioxide_factor * total_energy
        else:
            primary_emission = primary_energy_quantity * float(
                technology_row["primary_energy_emission_factor"],
            )
            secondary_emission = secondary_energy_quantity * float(
                technology_row["secondary_energy_emission_factor"],
            )
            total_emission = primary_emission + secondary_emission

        reported_emission = total_emission * self.current_reported_emission_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )

        if free_ets_balance is None:
            remaining_ets_allowance = self.yearly_ets_allowance(agent, year)
        else:
            remaining_ets_allowance = max(float(free_ets_balance), 0.0)
        covered_emission = min(remaining_ets_allowance, reported_emission)
        chargeable_emission = max(reported_emission - covered_emission, 0.0)
        remaining_ets_allowance = max(remaining_ets_allowance - reported_emission, 0.0)

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

    def yearly_ets_allowance(self, agent: MaritimeCargoShiplineAgent, year: int) -> float:
        allocation_factor = agent.scenario_value(
            "ets_allocation_factor",
            year,
            operator_name=agent.operator_name,
            default=1.0,
        )
        return agent.free_ets_allocation * max(1.0 - float(allocation_factor), 0.0)

    def annual_revenue(
        self,
        agent: MaritimeCargoShiplineAgent,
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
        cargo_capacity_tonnes = agent.cargo_capacity_tonnes(technology_row)
        return (
            cargo_capacity_tonnes
            * float(load_factor or 0.0)
            * trip_length
            * trip_days
            * float(freight_rate or 0.0)
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
        sox = self._partial_utility_sox(
            float(technology_row.get("sulphur_factor", 0.0) or 0.0),
        )
        co2 = self._partial_utility_co2(
            float(technology_row.get("carbondioxide_factor", 0.0) or 0.0),
        )
        nox = self._partial_utility_nox(float(technology_row["nitrogen_oxide_factor"]))
        smoke = self._partial_utility_smoke(float(technology_row["smoke_number_factor"]))
        return 0.30 * sox + 0.30 * co2 + 0.20 * nox + 0.20 * smoke

    def _partial_utility_sox(self, value: float) -> float:
        thresholds = (
            0.000878,
            0.00215,
            0.009563,
            0.01911,
            0.0200565,
            0.0238625,
            0.02865,
            0.04773,
        )
        scores = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2)
        if value <= 0.0:
            return 1.0
        for threshold, score in zip(thresholds, scores, strict=True):
            if value <= threshold:
                return score
        return 0.1

    def _partial_utility_co2(self, value: float) -> float:
        thresholds = (
            0.000135625,
            0.003612,
            0.0078484,
            0.01014839,
            0.018501,
            0.019621,
            0.026899792,
        )
        scores = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
        if value <= 0.0:
            return 1.0
        for threshold, score in zip(thresholds, scores, strict=True):
            if value <= threshold:
                return score
        return 0.2

    def _partial_utility_nox(self, value: float) -> float:
        thresholds = (
            0.0020308,
            0.010154,
            0.0386275,
            0.048391,
            0.05077,
            0.0549,
            0.06386,
            0.06834,
            0.0773,
        )
        scores = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
        if value <= 0.0:
            return 1.0
        for threshold, score in zip(thresholds, scores, strict=True):
            if value <= threshold:
                return score
        return 0.05

    def _partial_utility_smoke(self, value: float) -> float:
        thresholds = (
            0.000022,
            0.00036,
            0.0009,
            0.00294,
            0.0030829,
            0.0043288,
            0.00436,
            0.0072,
        )
        scores = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2)
        if value <= 0.0:
            return 1.0
        for threshold, score in zip(thresholds, scores, strict=True):
            if value <= threshold:
                return score
        return 0.1

    def is_candidate_available(
        self,
        agent: MaritimeCargoShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> bool:
        technology_name = clean_scope_value(technology_row["technology_name"])
        segment = clean_scope_value(operation_segment)
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
        biofuel_flag = 1.0
        if secondary_energy_carrier not in {"", "none"}:
            biofuel_flag = agent.scenario_value(
                "biofuel_availability",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_energy_carrier,
                saf_pathway=saf_pathway,
                default=1.0,
            )
        return bool(technology_flag) and bool(infrastructure_flag) and bool(biofuel_flag)

    # --- NATMDecisionScorer hooks -------------------------------------------------

    def _compute_revenue(
        self,
        agent: MaritimeCargoShiplineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        del asset
        return self.annual_revenue(agent, technology_row, year)

    def _additional_operating_costs(self, revenue: float, technology_row: pd.Series) -> float:
        maintenance_cost = revenue * float(technology_row["maintenance_cost_share"])
        crew_cost = revenue * 0.18
        port_fees = revenue * 0.08
        cargo_handling = revenue * 0.06
        return maintenance_cost + crew_cost + port_fees + cargo_handling

    def _asset_capacity(
        self,
        agent: MaritimeCargoShiplineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return agent.vessel_freight_tonne_km_capacity(asset, technology_row, year)

    def _segment_capacity(
        self,
        agent: MaritimeCargoShiplineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.segment_freight_tonne_km_capacity(segment, year)

    def _allocated_demand(
        self,
        agent: MaritimeCargoShiplineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.allocated_freight_tonne_km(segment, year)

    def _apply_technology(
        self,
        agent: MaritimeCargoShiplineAgent,
        row_index: int,
        technology_row: pd.Series,
        evaluation: CandidateEvaluation,
        year: int,
        *,
        action: str = "invest",
    ) -> None:
        agent.apply_technology_to_vessel(row_index, technology_row, evaluation, year, action=action)

    def _continue_operation(
        self,
        agent: MaritimeCargoShiplineAgent,
        row_index: int,
        evaluation: CandidateEvaluation,
        year: int,
    ) -> None:
        agent.continue_vessel_operation(row_index, evaluation, year)

    # --- Public per-sector aliases (external API preserved exactly) --------------

    def select_technology_for_vessel(
        self,
        agent: MaritimeCargoShiplineAgent,
        vessel: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        return self._select_technology_for_asset(
            agent,
            vessel,
            year,
            initial_ets_balance,
            row_index=row_index,
        )

    def replace_due_vessels(
        self,
        agent: MaritimeCargoShiplineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        self._replace_due_assets(agent, year, replacement_rows=replacement_rows)

    def add_growth_vessels(self, agent: MaritimeCargoShiplineAgent, year: int) -> None:
        self._add_growth_assets(agent, year)


class LegacyWeightedUtilityMaritimePassengerLogic(
    NATMDecisionScorer,
    MaritimePassengerDecisionLogic,
):
    name = LegacyWeightedUtilityLogic.name

    cabin_names = (
        "passenger_economy_class",
        "passenger_premium_class",
        "passenger_overnight_cabin",
        "passenger_business_class",
        "passenger_family_cabin",
    )

    def current_carbon_price(self, agent: MaritimePassengerShiplineAgent, year: int) -> float:
        scenario_price = agent.scenario_value("carbon_tax", year)
        if scenario_price is None:
            scenario_price = agent.scenario_value("carbon_price", year)
        if scenario_price is None:
            return float(agent.model.current_policy_signal.carbon_price)
        return max(float(scenario_price), float(agent.model.current_policy_signal.carbon_price))

    def current_biofuel_mandate(
        self,
        agent: MaritimePassengerShiplineAgent,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        secondary_carrier = clean_scope_value(technology_row.get("secondary_energy_carrier", ""))
        saf_pathway = clean_scope_value(technology_row.get("saf_pathway", ""))
        scenario_value = agent.scenario_value(
            "biofuel_mandate",
            year,
            secondary_energy_carrier=secondary_carrier,
            saf_pathway=saf_pathway,
        )
        if scenario_value is None:
            scenario_value = agent.scenario_value(
                "adoption_mandate",
                year,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
            )
        policy_mandate = float(agent.model.current_policy_signal.maritime.adoption_mandate)
        if scenario_value is None:
            return policy_mandate
        return clamp(max(float(scenario_value), policy_mandate))

    def current_reported_emission_share(
        self,
        agent: MaritimePassengerShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        scenario_value = agent.scenario_value(
            "reported_emission",
            year,
            country=agent.operator_country,
            operator_name=agent.operator_name,
            segment=clean_scope_value(operation_segment),
            technology_name=clean_scope_value(technology_row["technology_name"]),
            default=None,
        )
        if scenario_value is None:
            scenario_value = technology_row.get("reported_emission_factor", 1.0)
        return max(float(scenario_value or 0.0), 0.0)

    def current_clean_fuel_subsidy(self, agent: MaritimePassengerShiplineAgent) -> float:
        return float(agent.model.current_policy_signal.maritime.clean_fuel_subsidy)

    def effective_secondary_share(
        self,
        agent: MaritimePassengerShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        segment = clean_scope_value(operation_segment)
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
        elif (
            legacy_cap := agent.scenario_value(
                "maximum_secondary_energy",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
                default=None,
            )
        ) is not None:
            max_share = clamp(float(legacy_cap))

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
        if cap_active is None:
            cap_active = agent.scenario_value(
                "maximum_cap_secondary_energy",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_carrier,
                saf_pathway=saf_pathway,
                default=1.0 if max_share > 0.0 else 0.0,
            )
        if not bool(cap_active) or max_share <= 0.0:
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
            if mandate_active is None:
                mandate_active = agent.scenario_value(
                    "drop_in_fuel_mandate",
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
            return min(max_share, self.current_biofuel_mandate(agent, technology_row, year))
        return max_share

    def annual_operation_metrics(
        self,
        agent: MaritimePassengerShiplineAgent,
        vessel: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics:
        trip_length = float(technology_row["trip_length_km"])
        trip_days = float(technology_row["trip_days_per_year"])
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        total_distance = trip_length * trip_days
        total_energy = total_distance / kilometer_per_kwh

        operation_segment = clean_scope_value(vessel["segment"])
        secondary_share = self.effective_secondary_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )
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
        tertiary_price = agent.scenario_value(
            "tertiary_energy_price",
            year,
            country=agent.operator_country,
            secondary_energy_carrier=clean_scope_value(technology_row["secondary_energy_carrier"]),
            saf_pathway=clean_scope_value(technology_row["saf_pathway"]),
            default=None,
        )
        carbon_price = self.current_carbon_price(agent, year)
        clean_fuel_subsidy = self.current_clean_fuel_subsidy(agent)
        is_alternative = not agent.technology_catalog.is_conventional_row(technology_row)

        if int(technology_row["drop_in_fuel"]) == 1 and tertiary_price is not None:
            secondary_price = tertiary_price
        if is_alternative and secondary_energy_quantity > 0.0:
            secondary_price = float(secondary_price) * (1.0 - clean_fuel_subsidy)
        elif is_alternative:
            primary_price = float(primary_price) * (1.0 - clean_fuel_subsidy)

        primary_emission = primary_energy_quantity * float(
            technology_row["primary_energy_emission_factor"],
        )
        secondary_emission = secondary_energy_quantity * float(
            technology_row["secondary_energy_emission_factor"],
        )
        total_emission = primary_emission + secondary_emission
        reported_emission = total_emission * self.current_reported_emission_share(
            agent,
            technology_row,
            year,
            operation_segment,
        )

        if free_ets_balance is None:
            remaining_ets_allowance = self.yearly_ets_allowance(agent, year)
        else:
            remaining_ets_allowance = max(float(free_ets_balance), 0.0)
        covered_emission = min(remaining_ets_allowance, reported_emission)
        chargeable_emission = max(reported_emission - covered_emission, 0.0)
        remaining_ets_allowance = max(remaining_ets_allowance - reported_emission, 0.0)

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

    def yearly_ets_allowance(self, agent: MaritimePassengerShiplineAgent, year: int) -> float:
        allocation_factor = agent.scenario_value(
            "ets_allocation_factor",
            year,
            operator_name=agent.operator_name,
            default=1.0,
        )
        return agent.free_ets_allocation * max(1.0 - float(allocation_factor), 0.0)

    def annual_revenue(
        self,
        agent: MaritimePassengerShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> float:
        segment = clean_scope_value(operation_segment)
        annual_distance = float(technology_row["trip_length_km"]) * float(
            technology_row["trip_days_per_year"],
        )
        capacity_by_cabin = agent.passenger_capacity_by_cabin(technology_row)
        ticket_revenue = 0.0
        total_occupied_passengers = 0.0

        for cabin_name in self.cabin_names:
            capacity = capacity_by_cabin.get(cabin_name, 0.0)
            if capacity <= 0.0:
                continue
            occupancy = agent.cabin_occupancy(cabin_name, year, segment)
            ticket_rate = agent.cabin_ticket_rate(cabin_name, year, segment)
            occupied_passengers = capacity * occupancy
            total_occupied_passengers += occupied_passengers
            ticket_revenue += occupied_passengers * annual_distance * ticket_rate

        onboard_spending = agent.scenario_value(
            "onboard_spending",
            year,
            operator_name=agent.operator_name,
            segment=segment,
            default=None,
        )
        if onboard_spending is None:
            onboard_spending = agent.scenario_value(
                "onboard_spending",
                year,
                operator_name=agent.operator_name,
                default=0.0,
            )
        onboard_revenue = (
            total_occupied_passengers
            * annual_distance
            * float(
                onboard_spending or 0.0,
            )
        )
        return ticket_revenue + onboard_revenue

    def environmental_utility(self, technology_row: pd.Series) -> float:
        hydrocarbon = self._partial_utility_hydrocarbon(
            float(technology_row["hydrocarbon_factor"]),
        )
        carbon_monoxide = self._partial_utility_carbon_monoxide(
            float(technology_row["carbon_monoxide_factor"]),
        )
        nitrogen_oxide = self._partial_utility_nitrogen_oxide(
            float(technology_row["nitrogen_oxide_factor"]),
        )
        smoke_number = self._partial_utility_smoke_number(
            float(technology_row["smoke_number_factor"]),
        )
        co2_primary = self._partial_utility_co2_primary(
            float(technology_row["primary_energy_emission_factor"]),
        )
        co2_secondary = self._partial_utility_co2_secondary(
            float(technology_row["secondary_energy_emission_factor"]),
        )
        return (
            0.2 * hydrocarbon
            + 0.2 * carbon_monoxide
            + 0.2 * nitrogen_oxide
            + 0.2 * smoke_number
            + 0.1 * (co2_primary + co2_secondary)
        )

    def _partial_utility_hydrocarbon(self, value: float) -> float:
        if value <= 0.0:
            return 1.0
        if value <= 148.0:
            return 0.9
        if value <= 296.0:
            return 0.6
        if value <= 444.0:
            return 0.4
        if value <= 592.0:
            return 0.2
        return 0.0

    def _partial_utility_carbon_monoxide(self, value: float) -> float:
        if value <= 0.0:
            return 1.0
        if value <= 131.8:
            return 0.9
        if value <= 263.6:
            return 0.6
        if value <= 395.4:
            return 0.4
        if value <= 527.2:
            return 0.2
        return 0.0

    def _partial_utility_nitrogen_oxide(self, value: float) -> float:
        if value <= 0.0:
            return 1.0
        if value <= 16.78:
            return 0.9
        if value <= 33.56:
            return 0.6
        if value <= 50.34:
            return 0.4
        if value <= 67.12:
            return 0.2
        return 0.0

    def _partial_utility_smoke_number(self, value: float) -> float:
        if value <= 0.0:
            return 1.0
        if value <= 15.6:
            return 0.9
        if value <= 31.2:
            return 0.6
        if value <= 46.8:
            return 0.4
        if value <= 62.4:
            return 0.2
        return 0.0

    def _partial_utility_co2_primary(self, value: float) -> float:
        return 1.0 if value <= 0.0 else 0.0

    def _partial_utility_co2_secondary(self, value: float) -> float:
        return 1.0 if value <= 0.0 else 0.0

    def is_candidate_available(
        self,
        agent: MaritimePassengerShiplineAgent,
        technology_row: pd.Series,
        year: int,
        operation_segment: str,
    ) -> bool:
        technology_name = clean_scope_value(technology_row["technology_name"])
        segment = clean_scope_value(operation_segment)
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
        biofuel_flag = 1.0
        if secondary_energy_carrier not in {"", "none"}:
            biofuel_flag = agent.scenario_value(
                "biofuel_availability",
                year,
                country=agent.operator_country,
                segment=segment,
                technology_name=technology_name,
                secondary_energy_carrier=secondary_energy_carrier,
                saf_pathway=saf_pathway,
                default=1.0,
            )
        return bool(technology_flag) and bool(infrastructure_flag) and bool(biofuel_flag)

    # --- NATMDecisionScorer hooks -------------------------------------------------

    def _compute_revenue(
        self,
        agent: MaritimePassengerShiplineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return self.annual_revenue(agent, technology_row, year, str(asset["segment"]))

    def _additional_operating_costs(self, revenue: float, technology_row: pd.Series) -> float:
        uses_drop_in_branch = (
            int(technology_row["drop_in_fuel"]) == 1
            and float(technology_row["maximum_secondary_energy_share"]) > 0.0
        )
        maintenance_cost = revenue * float(technology_row["maintenance_cost_share"])
        crew_cost = revenue * 0.24
        port_fees = revenue * 0.10
        passenger_service_cost = 0.0 if uses_drop_in_branch else revenue * 0.10
        return maintenance_cost + crew_cost + port_fees + passenger_service_cost

    def _asset_capacity(
        self,
        agent: MaritimePassengerShiplineAgent,
        asset: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        return agent.vessel_passenger_km_capacity(asset, technology_row, year)

    def _segment_capacity(
        self,
        agent: MaritimePassengerShiplineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.segment_passenger_km_capacity(segment, year)

    def _allocated_demand(
        self,
        agent: MaritimePassengerShiplineAgent,
        segment: str,
        year: int,
    ) -> float:
        return agent.allocated_passenger_km(segment, year)

    def _apply_technology(
        self,
        agent: MaritimePassengerShiplineAgent,
        row_index: int,
        technology_row: pd.Series,
        evaluation: CandidateEvaluation,
        year: int,
        *,
        action: str = "invest",
    ) -> None:
        agent.apply_technology_to_vessel(row_index, technology_row, evaluation, year, action=action)

    def _continue_operation(
        self,
        agent: MaritimePassengerShiplineAgent,
        row_index: int,
        evaluation: CandidateEvaluation,
        year: int,
    ) -> None:
        agent.continue_vessel_operation(row_index, evaluation, year)

    def _payback_year_fallback(self, life_time: int, max_npv_year: int) -> int:
        """Maritime passenger uses the best-NPV-so-far year as its fallback,
        instead of the conservative life_time default every other sector uses."""
        del life_time
        return max_npv_year

    # --- Public per-sector aliases (external API preserved exactly) --------------

    def select_technology_for_vessel(
        self,
        agent: MaritimePassengerShiplineAgent,
        vessel: pd.Series,
        year: int,
        initial_ets_balance: float | None = None,
        *,
        row_index: int | None = None,
    ) -> tuple[pd.Series, CandidateEvaluation, str]:
        return self._select_technology_for_asset(
            agent,
            vessel,
            year,
            initial_ets_balance,
            row_index=row_index,
        )

    def replace_due_vessels(
        self,
        agent: MaritimePassengerShiplineAgent,
        year: int,
        *,
        replacement_rows: list[int] | None = None,
    ) -> None:
        self._replace_due_assets(agent, year, replacement_rows=replacement_rows)

    def add_growth_vessels(self, agent: MaritimePassengerShiplineAgent, year: int) -> None:
        self._add_growth_assets(agent, year)
