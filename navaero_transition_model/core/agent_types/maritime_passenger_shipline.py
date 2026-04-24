from __future__ import annotations

from typing import Any

import mesa
import pandas as pd

from navaero_transition_model.core.agent_types.base import BaseOperatorAgent
from navaero_transition_model.core.case_inputs import ScenarioTable, TechnologyCatalog
from navaero_transition_model.core.decision_logic import (
    build_maritime_passenger_decision_logic,
    clamp,
)
from navaero_transition_model.core.fleet_management import Fleet


class MaritimePassengerShiplineAgent(BaseOperatorAgent):
    sector_name = "maritime"
    application_name = "passenger"

    def __init__(
        self,
        model: mesa.Model,
        *,
        operator_name: str,
        operator_country: str,
        fleet_frame: pd.DataFrame,
        technology_catalog: TechnologyCatalog,
        scenario_table: ScenarioTable,
    ) -> None:
        super().__init__(
            model,
            operator_name=operator_name,
            operator_country=operator_country,
        )
        self.technology_catalog = technology_catalog
        self.scenario_table = scenario_table
        self.operator_economic_weight = self._fleet_value(
            fleet_frame,
            "operator_economic_weight",
            default=0.65,
        )
        self.operator_environmental_weight = self._fleet_value(
            fleet_frame,
            "operator_environmental_weight",
            default=0.35,
        )
        self.free_ets_allocation = self._fleet_value(
            fleet_frame,
            "free_ets_allocation",
            default=0.0,
        )
        self.peer_influence = self._fleet_value(
            fleet_frame,
            "peer_influence",
            default=0.0,
        )
        self.investment_logic_name = self._fleet_text_value(
            fleet_frame,
            "investment_logic",
            default="legacy_weighted_utility_maritime_passenger",
        )
        self.decision_logic = build_maritime_passenger_decision_logic(self.investment_logic_name)
        self.remaining_ets_allowance = 0.0
        self.technology_investment_cost: dict[tuple[int, str], float] = {}
        self.fleet = Fleet(
            fleet_frame,
            technology_catalog=self.technology_catalog,
            start_year=self.model.scenario.start_year,
        )
        self.update_existing_fleet(self.current_year)
        self.refresh_summary()

    def step(self) -> None:
        year = self.current_year
        self.decision_logic.step(self, year)
        self.refresh_summary()

    def _fleet_value(
        self,
        fleet_frame: pd.DataFrame,
        column: str,
        *,
        default: float,
    ) -> float:
        if column not in fleet_frame.columns:
            return default
        series = fleet_frame[column].dropna()
        if series.empty:
            return default
        return float(series.iloc[0])

    def _fleet_text_value(
        self,
        fleet_frame: pd.DataFrame,
        column: str,
        *,
        default: str,
    ) -> str:
        if column not in fleet_frame.columns:
            return default
        series = fleet_frame[column].dropna()
        if series.empty:
            return default
        value = str(series.iloc[0]).strip()
        return value or default

    def technology_row(self, technology_name: str, segment: str | None = None) -> pd.Series:
        del segment
        return self.technology_catalog.row_for(technology_name)

    def scenario_value(
        self,
        variable_name: str,
        year: int,
        *,
        default: float | None = None,
        **scope: str,
    ) -> float | None:
        return self.scenario_table.value(variable_name, year, default=default, **scope)

    def update_existing_fleet(
        self,
        year: int,
        *,
        excluded_indices: set[int] | None = None,
    ) -> None:
        starting_ets_allowance = self.decision_logic.yearly_ets_allowance(self, year)
        self.remaining_ets_allowance = self.fleet.update_operation_metrics(
            year=year,
            operation_metrics_fn=lambda vessel, technology_row, target_year, ets_balance: (
                self.decision_logic.annual_operation_metrics(
                    self,
                    vessel,
                    technology_row,
                    target_year,
                    ets_balance,
                )
            ),
            starting_ets_allowance=starting_ets_allowance,
            excluded_indices=excluded_indices,
        )

    def passenger_capacity_by_cabin(self, technology_row: pd.Series) -> dict[str, float]:
        return {
            "passenger_economy_class": float(
                technology_row.get("passenger_economy_class", 0.0) or 0.0,
            ),
            "passenger_premium_class": float(
                technology_row.get("passenger_premium_class", 0.0) or 0.0,
            ),
            "passenger_overnight_cabin": float(
                technology_row.get("passenger_overnight_cabin", 0.0) or 0.0,
            ),
            "passenger_business_class": float(
                technology_row.get("passenger_business_class", 0.0) or 0.0,
            ),
            "passenger_family_cabin": float(
                technology_row.get("passenger_family_cabin", 0.0) or 0.0,
            ),
        }

    def cabin_occupancy(self, cabin_name: str, year: int, segment: str) -> float:
        variable_name = f"{cabin_name}_occupancy"
        occupancy = self.scenario_value(
            variable_name,
            year,
            operator_name=self.operator_name,
            segment=segment,
            default=None,
        )
        if occupancy is None:
            occupancy = self.scenario_value(
                variable_name,
                year,
                operator_name=self.operator_name,
                default=0.0,
            )
        return clamp(float(occupancy or 0.0))

    def cabin_ticket_rate(self, cabin_name: str, year: int, segment: str) -> float:
        variable_name = f"{cabin_name}_ticket_rate"
        ticket_rate = self.scenario_value(
            variable_name,
            year,
            operator_name=self.operator_name,
            segment=segment,
            default=None,
        )
        if ticket_rate is None:
            ticket_rate = self.scenario_value(
                variable_name,
                year,
                operator_name=self.operator_name,
                default=0.0,
            )
        return float(ticket_rate or 0.0)

    def effective_load_factor(
        self,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        segment = str(technology_row["segment"])
        cabin_capacity = self.passenger_capacity_by_cabin(technology_row)
        total_capacity = max(sum(cabin_capacity.values()), 1.0)
        occupied_capacity = 0.0
        for cabin_name, capacity in cabin_capacity.items():
            occupied_capacity += capacity * self.cabin_occupancy(cabin_name, year, segment)
        return clamp(occupied_capacity / total_capacity)

    def vessel_passenger_km_capacity(
        self,
        vessel: pd.Series,
        technology_row: pd.Series,
        year: int,
    ) -> float:
        active_status = str(vessel.get("status", "")).strip().lower()
        if active_status == "parked":
            return 0.0

        total_capacity = sum(self.passenger_capacity_by_cabin(technology_row).values())
        trip_length = float(technology_row["trip_length_km"])
        trip_days = float(technology_row["trip_days_per_year"])
        load_factor = self.effective_load_factor(technology_row, year)
        return total_capacity * trip_length * trip_days * load_factor

    def segment_passenger_km_capacity(self, segment: str, year: int) -> float:
        segment_rows = self.fleet.frame.loc[self.fleet.frame["segment"] == segment]
        total_capacity = 0.0
        for _, vessel in segment_rows.iterrows():
            technology_row = self.technology_row(
                technology_name=str(vessel["current_technology"]),
                segment=str(vessel["segment"]),
            )
            total_capacity += self.vessel_passenger_km_capacity(
                vessel,
                technology_row,
                year,
            )
        return total_capacity

    def allocated_passenger_km(self, segment: str, year: int) -> float:
        passenger_km_demand = self.scenario_value(
            "passenger_km_demand",
            year,
            country=self.operator_country,
            segment=segment,
            default=0.0,
        )
        operator_market_share = self.scenario_value(
            "operator_market_share",
            year,
            country=self.operator_country,
            operator_name=self.operator_name,
            segment=segment,
            default=0.0,
        )
        return float(passenger_km_demand) * float(operator_market_share)

    def planned_delivery_rows(self, segment: str, year: int) -> pd.DataFrame:
        return self.scenario_table.matching_rows(
            "planned_delivery_count",
            year,
            country=self.operator_country,
            operator_name=self.operator_name,
            segment=segment,
        )

    def segment_template(self, segment: str) -> pd.Series | None:
        segment_rows = self.fleet.frame.loc[self.fleet.frame["segment"] == segment]
        if segment_rows.empty:
            return None

        active_rows = segment_rows.loc[
            segment_rows["status"].astype(str).str.strip().str.lower() == "active"
        ]
        if not active_rows.empty:
            return active_rows.iloc[0].copy()
        return segment_rows.iloc[0].copy()

    def apply_technology_to_vessel(
        self,
        row_index: int,
        technology_row: pd.Series,
        evaluation,
        year: int,
    ) -> None:
        self.fleet.apply_technology(
            row_index,
            technology_row,
            evaluation,
            year=year,
        )
        self.remaining_ets_allowance = evaluation.remaining_ets_allowance
        self.technology_investment_cost[(year, str(technology_row["technology_name"]))] = float(
            technology_row["capex_eur"],
        )

    def refresh_summary(self) -> None:
        current_rows = self.fleet.technology_rows()

        conventional = 0
        alternative = 0
        for technology_row in current_rows:
            is_conventional = self.technology_catalog.is_conventional_row(technology_row)
            if is_conventional:
                conventional += 1
            else:
                alternative += 1

        self.conventional_assets = float(conventional)
        self.alternative_assets = float(alternative)
        self.infrastructure_readiness = self.environment_signal.infrastructure_readiness
        self.mandate_share = float(self.model.current_policy_signal.maritime.adoption_mandate)
        self.policy_support = clamp(
            0.55 * float(self.model.current_policy_signal.maritime.clean_fuel_subsidy)
            + 0.45 * self.mandate_share,
        )

        operating_costs = self.fleet.frame.get("effective_operating_cost", pd.Series(dtype=float))
        average_cost = float(operating_costs.mean()) if not operating_costs.empty else 0.0

        self.effective_conventional_cost = average_cost
        self.effective_alternative_cost = average_cost * max(1.0 - self.alternative_share, 0.5)
        self.transition_pressure = clamp(
            0.45 * self.alternative_share
            + 0.20 * self.infrastructure_readiness
            + 0.20 * self.policy_support
            + 0.15 * self.environment_signal.policy_alignment,
        )

    def fleet_snapshot(self, year: int | None = None) -> pd.DataFrame:
        snapshot_year = self.current_year if year is None else year
        return self.fleet.snapshot(
            year=snapshot_year,
            sector_name=self.sector_name,
            application_name=self.application_name,
            operator_name=self.operator_name,
            operator_country=self.operator_country,
            investment_logic=self.investment_logic_name,
        )

    def get_output_metadata(self) -> dict[str, Any]:
        metadata = super().get_output_metadata()
        metadata["investment_logic"] = self.investment_logic_name
        return metadata
