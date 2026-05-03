from __future__ import annotations

import pandas as pd

from navaero_transition_model.core.case_inputs import TechnologyCatalog
from navaero_transition_model.core.decision_logic.base import CandidateEvaluation


class Fleet:
    def __init__(
        self,
        dataframe: pd.DataFrame,
        *,
        technology_catalog: TechnologyCatalog,
        start_year: int,
    ) -> None:
        self.technology_catalog = technology_catalog
        self._frame = dataframe.reset_index(drop=True).copy()
        self._prepare(start_year)

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def __len__(self) -> int:
        return len(self._frame)

    def _prepare(self, start_year: int) -> None:
        if "current_technology" not in self._frame.columns:
            self._frame["current_technology"] = self._frame["segment"].map(
                lambda segment: self.technology_catalog.default_for_operation(segment=str(segment)),
            )
        else:
            self._frame["current_technology"] = self._frame["current_technology"].fillna(
                self._frame["segment"].map(
                    lambda segment: self.technology_catalog.default_for_operation(
                        segment=str(segment),
                    ),
                ),
            )

        self._frame["aircraft_id"] = self._frame["aircraft_id"].astype(int)
        if "vessel_id" in self._frame.columns:
            self._frame["vessel_id"] = self._frame["vessel_id"].fillna(self._frame["aircraft_id"])
        self._frame["replacement_year"] = self._frame.apply(
            lambda aircraft: self._initial_replacement_year(aircraft, start_year),
            axis=1,
        )
        self._frame["total_emission"] = 0.0
        self._frame["primary_energy_consumption"] = 0.0
        self._frame["secondary_energy_consumption"] = 0.0
        self._frame["economic_utility"] = 0.0
        self._frame["environmental_utility"] = 0.0
        self._frame["total_utility"] = 0.0
        self._frame["investment_cost_eur"] = 0.0
        self._frame["investment_year"] = pd.NA
        self._frame["effective_operating_cost"] = 0.0
        self._frame["chargeable_emission"] = 0.0
        self._frame["remaining_ets_allocation"] = 0.0
        self._frame["primary_energy_carrier"] = self._frame.apply(
            lambda aircraft: self.technology_catalog.row_for(
                technology_name=str(aircraft["current_technology"]),
            )["primary_energy_carrier"],
            axis=1,
        )
        self._frame["secondary_energy_carrier"] = self._frame.apply(
            lambda aircraft: self.technology_catalog.row_for(
                technology_name=str(aircraft["current_technology"]),
            )["secondary_energy_carrier"],
            axis=1,
        )
        self._frame["saf_pathway"] = self._frame.apply(
            lambda aircraft: self.technology_catalog.row_for(
                technology_name=str(aircraft["current_technology"]),
            )["saf_pathway"],
            axis=1,
        )
        self.assign_baseline_activity_profiles()
        self.apply_activity_fallbacks()
        self.estimate_baseline_energy_demand()

    def assign_baseline_activity_profiles(self) -> None:
        default_columns = {
            "registration": pd.NA,
            "icao24": pd.NA,
            "is_german_flag": pd.NA,
            "annual_flights_base": pd.NA,
            "annual_distance_km_base": pd.NA,
            "domestic_activity_share_base": pd.NA,
            "international_activity_share_base": pd.NA,
            "mean_stage_length_km_base": pd.NA,
            "fuel_burn_per_year_base": pd.NA,
            "baseline_energy_demand": pd.NA,
            "airport_allocation_group": pd.NA,
            "main_hub_base": pd.NA,
            "match_confidence": pd.NA,
            "match_method": pd.NA,
            "activity_assignment_method": pd.NA,
            "openap_type": pd.NA,
            "number_of_trips": pd.NA,
            "total_distance_km": pd.NA,
            "total_fuel_kg": pd.NA,
            "total_energy_mwh": pd.NA,
            "total_co2_kg": pd.NA,
            "total_nox_kg": pd.NA,
            "fuel_kg_per_km": pd.NA,
            "energy_mwh_per_km": pd.NA,
            "co2_kg_per_km": pd.NA,
            "average_flight_distance_km": pd.NA,
            "average_fuel_kg_per_flight": pd.NA,
        }
        for column, default in default_columns.items():
            if column not in self._frame.columns:
                self._frame[column] = default
        self._frame["annual_flights_base"] = pd.to_numeric(
            self._frame["annual_flights_base"],
            errors="coerce",
        )
        self._frame["annual_distance_km_base"] = pd.to_numeric(
            self._frame["annual_distance_km_base"],
            errors="coerce",
        )
        self._frame["domestic_activity_share_base"] = pd.to_numeric(
            self._frame["domestic_activity_share_base"],
            errors="coerce",
        )
        self._frame["international_activity_share_base"] = pd.to_numeric(
            self._frame["international_activity_share_base"],
            errors="coerce",
        )
        self._frame["mean_stage_length_km_base"] = pd.to_numeric(
            self._frame["mean_stage_length_km_base"],
            errors="coerce",
        )
        self._frame["fuel_burn_per_year_base"] = pd.to_numeric(
            self._frame["fuel_burn_per_year_base"],
            errors="coerce",
        )
        self._frame["baseline_energy_demand"] = pd.to_numeric(
            self._frame["baseline_energy_demand"],
            errors="coerce",
        )
        self._frame["match_confidence"] = pd.to_numeric(
            self._frame["match_confidence"],
            errors="coerce",
        )
        for column in (
            "number_of_trips",
            "total_distance_km",
            "total_fuel_kg",
            "total_energy_mwh",
            "total_co2_kg",
            "total_nox_kg",
            "fuel_kg_per_km",
            "energy_mwh_per_km",
            "co2_kg_per_km",
            "average_flight_distance_km",
            "average_fuel_kg_per_flight",
        ):
            self._frame[column] = pd.to_numeric(self._frame[column], errors="coerce")
        self._frame["main_hub_base"] = self._frame["main_hub_base"].combine_first(
            self._frame.get("main_hub", pd.Series(index=self._frame.index, dtype=object)),
        )

    def _needs_positive_activity_fallback(self, row_index: int, column: str) -> bool:
        value = pd.to_numeric(
            pd.Series([self._frame.loc[row_index, column]]),
            errors="coerce",
        ).iloc[0]
        return pd.isna(value) or float(value) <= 0.0

    def apply_activity_fallbacks(self) -> None:
        for row_index, aircraft in self._frame.iterrows():
            technology_row = self.technology_row(
                technology_name=str(aircraft["current_technology"]),
            )
            segment = str(aircraft.get("segment", "")).strip().lower()
            if self._needs_positive_activity_fallback(row_index, "mean_stage_length_km_base"):
                self._frame.loc[row_index, "mean_stage_length_km_base"] = float(
                    technology_row["trip_length_km"],
                )
            if self._needs_positive_activity_fallback(row_index, "annual_flights_base"):
                self._frame.loc[row_index, "annual_flights_base"] = float(
                    technology_row["trip_days_per_year"],
                )
            if self._needs_positive_activity_fallback(row_index, "annual_distance_km_base"):
                self._frame.loc[row_index, "annual_distance_km_base"] = float(
                    self._frame.loc[row_index, "annual_flights_base"]
                ) * float(self._frame.loc[row_index, "mean_stage_length_km_base"])
            if pd.isna(self._frame.loc[row_index, "domestic_activity_share_base"]):
                if segment == "short":
                    domestic_share = 0.65
                elif segment == "medium":
                    domestic_share = 0.25
                else:
                    domestic_share = 0.0
                self._frame.loc[row_index, "domestic_activity_share_base"] = domestic_share
            if pd.isna(self._frame.loc[row_index, "international_activity_share_base"]):
                domestic_share = float(
                    self._frame.loc[row_index, "domestic_activity_share_base"] or 0.0,
                )
                self._frame.loc[row_index, "international_activity_share_base"] = max(
                    1.0 - domestic_share,
                    0.0,
                )
            if pd.isna(self._frame.loc[row_index, "airport_allocation_group"]):
                self._frame.loc[row_index, "airport_allocation_group"] = (
                    self._frame.loc[row_index, "main_hub_base"]
                    if pd.notna(self._frame.loc[row_index, "main_hub_base"])
                    else segment
                )
            if pd.isna(self._frame.loc[row_index, "activity_assignment_method"]):
                self._frame.loc[row_index, "activity_assignment_method"] = "fallback_default"

    def estimate_baseline_energy_demand(self) -> None:
        for row_index, aircraft in self._frame.iterrows():
            existing_energy = pd.to_numeric(
                pd.Series([self._frame.loc[row_index, "baseline_energy_demand"]]),
                errors="coerce",
            ).iloc[0]
            if pd.notna(existing_energy) and float(existing_energy) > 0.0:
                if self._needs_positive_activity_fallback(row_index, "fuel_burn_per_year_base"):
                    self._frame.loc[row_index, "fuel_burn_per_year_base"] = self._frame.loc[
                        row_index,
                        "baseline_energy_demand",
                    ]
                continue
            technology_row = self.technology_row(
                technology_name=str(aircraft["current_technology"]),
            )
            annual_distance = pd.to_numeric(
                pd.Series([self._frame.loc[row_index, "annual_distance_km_base"]]),
                errors="coerce",
            ).iloc[0]
            if pd.isna(annual_distance):
                continue
            kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
            baseline_energy = float(annual_distance) / kilometer_per_kwh
            self._frame.loc[row_index, "baseline_energy_demand"] = baseline_energy
            if self._needs_positive_activity_fallback(row_index, "fuel_burn_per_year_base"):
                self._frame.loc[row_index, "fuel_burn_per_year_base"] = baseline_energy

    def annual_flights_for(self, aircraft: pd.Series, technology_row: pd.Series) -> float:
        annual_flights = pd.to_numeric(
            pd.Series([aircraft.get("annual_flights_base", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(annual_flights):
            return float(annual_flights)
        return float(technology_row["trip_days_per_year"])

    def mean_stage_length_km_for(self, aircraft: pd.Series, technology_row: pd.Series) -> float:
        stage_length = pd.to_numeric(
            pd.Series([aircraft.get("mean_stage_length_km_base", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(stage_length):
            return float(stage_length)
        return float(technology_row["trip_length_km"])

    def annual_distance_km_for(self, aircraft: pd.Series, technology_row: pd.Series) -> float:
        annual_distance = pd.to_numeric(
            pd.Series([aircraft.get("annual_distance_km_base", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(annual_distance):
            return float(annual_distance)
        return self.annual_flights_for(aircraft, technology_row) * self.mean_stage_length_km_for(
            aircraft,
            technology_row,
        )

    def baseline_energy_demand_for(self, aircraft: pd.Series, technology_row: pd.Series) -> float:
        baseline_energy = pd.to_numeric(
            pd.Series([aircraft.get("baseline_energy_demand", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(baseline_energy):
            return float(baseline_energy)
        kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
        return self.annual_distance_km_for(aircraft, technology_row) / kilometer_per_kwh

    def _initial_replacement_year(self, aircraft: pd.Series, start_year: int) -> int:
        technology = self.technology_catalog.row_for(
            technology_name=str(aircraft["current_technology"]),
        )
        age = float(
            aircraft.get(
                "aircraft_age_years",
                aircraft.get("vessel_age_years", 0.0),
            ),
        )
        remaining_lifetime = max(int(technology["lifetime_years"] - round(age)), 0)
        return start_year + remaining_lifetime

    def technology_row(self, technology_name: str, segment: str | None = None) -> pd.Series:
        del segment
        return self.technology_catalog.row_for(technology_name)

    def update_operation_metrics(
        self,
        *,
        year: int,
        operation_metrics_fn,
        starting_ets_allowance: float = 0.0,
        excluded_indices: set[int] | None = None,
    ) -> float:
        remaining_ets_allowance = max(float(starting_ets_allowance), 0.0)
        skipped_indices = excluded_indices or set()
        for row_index, aircraft in self._frame.iterrows():
            if int(row_index) in skipped_indices:
                continue
            technology_row = self.technology_row(
                technology_name=str(aircraft["current_technology"]),
            )
            operation_metrics = operation_metrics_fn(
                aircraft,
                technology_row,
                year,
                remaining_ets_allowance,
            )
            remaining_ets_allowance = operation_metrics.remaining_ets_allowance
            self._frame.loc[row_index, "total_emission"] = operation_metrics.total_emission
            self._frame.loc[row_index, "primary_energy_consumption"] = (
                operation_metrics.primary_energy_quantity
            )
            self._frame.loc[row_index, "secondary_energy_consumption"] = (
                operation_metrics.secondary_energy_quantity
            )
            self._frame.loc[row_index, "chargeable_emission"] = (
                operation_metrics.chargeable_emission
            )
            self._frame.loc[row_index, "remaining_ets_allocation"] = remaining_ets_allowance
            self._frame.loc[row_index, "primary_energy_carrier"] = technology_row[
                "primary_energy_carrier"
            ]
            self._frame.loc[row_index, "secondary_energy_carrier"] = technology_row[
                "secondary_energy_carrier"
            ]
            self._frame.loc[row_index, "saf_pathway"] = technology_row["saf_pathway"]
            self._frame.loc[row_index, "effective_operating_cost"] = operation_metrics.total_cost
        return remaining_ets_allowance

    def due_replacement_indices(self, year: int, *, acceleration_window: int = 0) -> list[int]:
        replacement_rows: list[int] = []
        for row_index, aircraft in self._frame.iterrows():
            is_conventional = self.technology_catalog.is_conventional(
                str(aircraft["current_technology"]),
            )
            due_now = int(aircraft["replacement_year"]) <= year
            early_replacement = (
                is_conventional
                and acceleration_window > 0
                and int(aircraft["replacement_year"]) <= year + acceleration_window
            )
            if due_now or early_replacement:
                replacement_rows.append(int(row_index))
        return replacement_rows

    def apply_technology(
        self,
        row_index: int,
        technology_row: pd.Series,
        evaluation: CandidateEvaluation,
        *,
        year: int,
    ) -> None:
        self._frame.loc[row_index, "current_technology"] = technology_row["technology_name"]
        self._frame.loc[row_index, "primary_energy_carrier"] = technology_row[
            "primary_energy_carrier"
        ]
        self._frame.loc[row_index, "secondary_energy_carrier"] = technology_row[
            "secondary_energy_carrier"
        ]
        self._frame.loc[row_index, "saf_pathway"] = technology_row["saf_pathway"]
        self._frame.loc[row_index, "replacement_year"] = year + int(
            technology_row["lifetime_years"],
        )
        self._frame.loc[row_index, "aircraft_age_years"] = 0.0
        if "vessel_age_years" in self._frame.columns:
            self._frame.loc[row_index, "vessel_age_years"] = 0.0
        self._frame.loc[row_index, "total_emission"] = evaluation.total_emission
        self._frame.loc[row_index, "primary_energy_consumption"] = (
            evaluation.primary_energy_quantity
        )
        self._frame.loc[row_index, "secondary_energy_consumption"] = (
            evaluation.secondary_energy_quantity
        )
        self._frame.loc[row_index, "chargeable_emission"] = evaluation.chargeable_emission
        self._frame.loc[row_index, "remaining_ets_allocation"] = evaluation.remaining_ets_allowance
        self._frame.loc[row_index, "economic_utility"] = evaluation.economic_utility
        self._frame.loc[row_index, "environmental_utility"] = evaluation.environmental_utility
        self._frame.loc[row_index, "total_utility"] = evaluation.total_utility
        self._frame.loc[row_index, "investment_cost_eur"] = float(technology_row["capex_eur"])
        self._frame.loc[row_index, "investment_year"] = year
        self._frame.loc[row_index, "effective_operating_cost"] = (
            evaluation.current_year_operating_cost
        )

    def next_aircraft_id(self) -> int:
        return int(self._frame["aircraft_id"].max()) + 1 if not self._frame.empty else 1000

    def add_aircraft_from_template(self, template: pd.Series, *, next_aircraft_id: int) -> int:
        new_row = template.copy()
        new_row["aircraft_id"] = next_aircraft_id
        if "vessel_id" in new_row.index:
            new_row["vessel_id"] = next_aircraft_id
        new_row["status"] = "Active"
        self._frame = pd.concat([self._frame, pd.DataFrame([new_row])], ignore_index=True)
        return len(self._frame) - 1

    def technology_rows(self) -> list[pd.Series]:
        current_rows: list[pd.Series] = []
        for _, aircraft in self._frame.iterrows():
            current_rows.append(
                self.technology_row(
                    technology_name=str(aircraft["current_technology"]),
                ),
            )
        return current_rows

    def snapshot(
        self,
        *,
        year: int,
        sector_name: str,
        application_name: str,
        operator_name: str,
        operator_country: str,
        investment_logic: str,
        decision_attitude: str = "risk_neutral",
    ) -> pd.DataFrame:
        fleet_snapshot = self._frame.copy()
        fleet_snapshot["year"] = year
        fleet_snapshot["sector_name"] = sector_name
        fleet_snapshot["application_name"] = application_name
        fleet_snapshot["operator_name"] = operator_name
        fleet_snapshot["operator_country"] = operator_country
        fleet_snapshot["investment_logic"] = investment_logic
        fleet_snapshot["decision_attitude"] = decision_attitude
        preferred_order = [
            "year",
            "sector_name",
            "application_name",
            "operator_name",
            "operator_country",
            "investment_logic",
            "decision_attitude",
        ]
        remaining_columns = [
            column for column in fleet_snapshot.columns if column not in preferred_order
        ]
        return fleet_snapshot[preferred_order + remaining_columns]
