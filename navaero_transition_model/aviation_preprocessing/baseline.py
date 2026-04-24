from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import ensure_parent_dir
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner
from navaero_transition_model.core.case_inputs import TechnologyCatalog


@dataclass
class AviationBaselineOutputs:
    enriched_stock: pd.DataFrame
    activity_profiles: pd.DataFrame


@dataclass
class AviationBaselineBuilder:
    stock_cleaner: AviationStockCleaner = field(default_factory=AviationStockCleaner)

    def _row_assignment(
        self,
        stock_row: pd.Series,
        registration_profiles: pd.DataFrame,
        operator_type_profiles: pd.DataFrame,
        type_profiles: pd.DataFrame,
    ) -> tuple[dict[str, object], str]:
        registration = str(stock_row.get("registration", "")).strip()
        icao24 = str(stock_row.get("icao24", "")).strip()
        aircraft_type = str(stock_row.get("aircraft_type", "")).strip().upper()
        operator_name = str(stock_row.get("operator_name", "")).strip()
        segment = str(stock_row.get("segment", "")).strip()

        if not registration_profiles.empty:
            registration_match = registration_profiles.loc[
                (
                    registration_profiles["registration"].astype(str).str.strip().eq(registration)
                    & registration_profiles["icao24"].astype(str).str.strip().eq(icao24)
                )
                | (
                    (registration != "")
                    & registration_profiles["registration"].astype(str).str.strip().eq(registration)
                )
                | (
                    (icao24 != "")
                    & registration_profiles["icao24"].astype(str).str.strip().eq(icao24)
                )
            ]
            if not registration_match.empty:
                return registration_match.iloc[0].to_dict(), "registration"

        if not operator_type_profiles.empty:
            operator_match = operator_type_profiles.loc[
                operator_type_profiles["operator_name"].astype(str).str.strip().eq(operator_name)
                & operator_type_profiles["typecode"].astype(str).str.strip().eq(aircraft_type)
            ]
            if not operator_match.empty:
                return operator_match.iloc[0].to_dict(), "operator_type"

        if not type_profiles.empty:
            type_match = type_profiles.loc[
                type_profiles["typecode"].astype(str).str.strip().eq(aircraft_type)
            ]
            if not type_match.empty:
                return type_match.iloc[0].to_dict(), "type"

        return {"segment": segment}, "segment"

    def build(
        self,
        *,
        stock_input_path: str | Path,
        registration_profiles_path: str
        | Path
        | None = "data/processed/aviation/aviation_activity_profiles_by_registration.csv",
        operator_type_profiles_path: str
        | Path
        | None = "data/processed/aviation/aviation_activity_profiles_by_operator_type.csv",
        type_profiles_path: str
        | Path
        | None = "data/processed/aviation/aviation_activity_profiles_by_type.csv",
        technology_catalog_path: str | Path | None = None,
        calibration_targets_path: str | Path | None = None,
        output_stock_path: str | Path = "data/processed/aviation/aviation_fleet_stock_enriched.csv",
        output_activity_profiles_path: str
        | Path = "data/processed/aviation/aviation_activity_profiles.csv",
    ) -> AviationBaselineOutputs:
        stock = self.stock_cleaner.clean(stock_input_path)
        for column in (
            "registration",
            "icao24",
            "airport_allocation_group",
            "main_hub_base",
            "activity_assignment_method",
        ):
            if column not in stock.columns:
                stock[column] = pd.Series(pd.NA, index=stock.index, dtype=object)
            else:
                stock[column] = stock[column].astype(object)
        registration_profiles = (
            pd.read_csv(registration_profiles_path)
            if registration_profiles_path is not None and Path(registration_profiles_path).exists()
            else pd.DataFrame()
        )
        operator_type_profiles = (
            pd.read_csv(operator_type_profiles_path)
            if operator_type_profiles_path is not None
            and Path(operator_type_profiles_path).exists()
            else pd.DataFrame()
        )
        type_profiles = (
            pd.read_csv(type_profiles_path)
            if type_profiles_path is not None and Path(type_profiles_path).exists()
            else pd.DataFrame()
        )

        technology_catalog = (
            TechnologyCatalog.from_csv(technology_catalog_path)
            if technology_catalog_path is not None and Path(technology_catalog_path).exists()
            else None
        )

        profile_rows: list[dict[str, object]] = []
        for index, stock_row in stock.iterrows():
            matched_profile, assignment_method = self._row_assignment(
                stock_row,
                registration_profiles,
                operator_type_profiles,
                type_profiles,
            )
            annual_departures = float(matched_profile.get("annual_departures", 0.0) or 0.0)
            annual_distance = float(matched_profile.get("annual_distance_km", 0.0) or 0.0)
            mean_stage_length = float(
                matched_profile.get(
                    "average_route_distance_km",
                    matched_profile.get("mean_stage_length_km_base", 0.0),
                )
                or 0.0,
            )
            if annual_distance <= 0.0 and annual_departures > 0.0 and mean_stage_length > 0.0:
                annual_distance = annual_departures * mean_stage_length

            profile = {
                "aircraft_id": stock_row["aircraft_id"],
                "registration": stock_row.get("registration", ""),
                "icao24": stock_row.get("icao24", ""),
                "operator_name": stock_row.get("operator_name", ""),
                "aircraft_type": stock_row.get("aircraft_type", ""),
                "segment": stock_row.get("segment", ""),
                "annual_flights_base": annual_departures,
                "annual_distance_km_base": annual_distance,
                "domestic_activity_share_base": matched_profile.get("domestic_share", pd.NA),
                "international_activity_share_base": matched_profile.get(
                    "international_share", pd.NA
                ),
                "mean_stage_length_km_base": mean_stage_length
                if mean_stage_length > 0.0
                else pd.NA,
                "airport_allocation_group": matched_profile.get(
                    "origin",
                    matched_profile.get("typecode", stock_row.get("segment", pd.NA)),
                ),
                "main_hub_base": matched_profile.get("origin", stock_row.get("main_hub", pd.NA)),
                "activity_assignment_method": assignment_method,
            }
            if technology_catalog is not None and annual_distance > 0.0:
                technology_row = technology_catalog.row_for(
                    str(
                        stock_row.get(
                            "current_technology",
                            technology_catalog.default_for_operation(
                                segment=str(stock_row["segment"]),
                            ),
                        )
                    ),
                )
                kilometer_per_kwh = max(float(technology_row["kilometer_per_kwh"]), 1e-6)
                profile["baseline_energy_demand"] = annual_distance / kilometer_per_kwh
                profile["fuel_burn_per_year_base"] = profile["baseline_energy_demand"]
            else:
                profile["baseline_energy_demand"] = pd.NA
                profile["fuel_burn_per_year_base"] = pd.NA
            profile_rows.append(profile)
            for column, value in profile.items():
                if column != "aircraft_id":
                    stock.loc[index, column] = value

        if calibration_targets_path is not None and Path(calibration_targets_path).exists():
            calibration_targets = pd.read_csv(calibration_targets_path)
            factor_series = pd.to_numeric(
                calibration_targets.get("calibration_factor_german_flag", pd.Series(dtype=float)),
                errors="coerce",
            ).dropna()
            if not factor_series.empty:
                factor = float(factor_series.iloc[0])
                german_flag_mask = (
                    stock.get("is_german_flag", pd.Series(False, index=stock.index))
                    .fillna(False)
                    .astype(bool)
                )
                stock.loc[german_flag_mask, "baseline_energy_demand"] = (
                    pd.to_numeric(
                        stock.loc[german_flag_mask, "baseline_energy_demand"],
                        errors="coerce",
                    )
                    * factor
                )
                stock.loc[german_flag_mask, "fuel_burn_per_year_base"] = (
                    pd.to_numeric(
                        stock.loc[german_flag_mask, "fuel_burn_per_year_base"],
                        errors="coerce",
                    )
                    * factor
                )

        activity_profiles = pd.DataFrame(profile_rows)
        ensure_parent_dir(output_stock_path)
        stock.to_csv(output_stock_path, index=False)
        ensure_parent_dir(output_activity_profiles_path)
        activity_profiles.to_csv(output_activity_profiles_path, index=False)
        return AviationBaselineOutputs(
            enriched_stock=stock.reset_index(drop=True),
            activity_profiles=activity_profiles.reset_index(drop=True),
        )
