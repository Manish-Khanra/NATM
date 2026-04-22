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
                self.technology_catalog.default_for_segment,
            )
        else:
            self._frame["current_technology"] = self._frame["current_technology"].fillna(
                self._frame["segment"].map(self.technology_catalog.default_for_segment),
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
                segment=str(aircraft["segment"]),
            )["primary_energy_carrier"],
            axis=1,
        )
        self._frame["secondary_energy_carrier"] = self._frame.apply(
            lambda aircraft: self.technology_catalog.row_for(
                technology_name=str(aircraft["current_technology"]),
                segment=str(aircraft["segment"]),
            )["secondary_energy_carrier"],
            axis=1,
        )
        self._frame["saf_pathway"] = self._frame.apply(
            lambda aircraft: self.technology_catalog.row_for(
                technology_name=str(aircraft["current_technology"]),
                segment=str(aircraft["segment"]),
            )["saf_pathway"],
            axis=1,
        )

    def _initial_replacement_year(self, aircraft: pd.Series, start_year: int) -> int:
        technology = self.technology_catalog.row_for(
            technology_name=str(aircraft["current_technology"]),
            segment=str(aircraft["segment"]),
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
        return self.technology_catalog.row_for(technology_name, segment)

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
                segment=str(aircraft["segment"]),
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
                str(aircraft["segment"]),
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
                    segment=str(aircraft["segment"]),
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
    ) -> pd.DataFrame:
        fleet_snapshot = self._frame.copy()
        fleet_snapshot["year"] = year
        fleet_snapshot["sector_name"] = sector_name
        fleet_snapshot["application_name"] = application_name
        fleet_snapshot["operator_name"] = operator_name
        fleet_snapshot["operator_country"] = operator_country
        fleet_snapshot["investment_logic"] = investment_logic
        preferred_order = [
            "year",
            "sector_name",
            "application_name",
            "operator_name",
            "operator_country",
            "investment_logic",
        ]
        remaining_columns = [
            column for column in fleet_snapshot.columns if column not in preferred_order
        ]
        return fleet_snapshot[preferred_order + remaining_columns]
