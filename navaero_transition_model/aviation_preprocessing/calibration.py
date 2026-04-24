from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import ensure_parent_dir
from navaero_transition_model.aviation_preprocessing.filters import filter_german_flag_fleet

CALIBRATION_COLUMN_ALIASES = {
    "annual_total_aviation_fuel_consumption": "official_total_energy_demand",
    "annual_total_aviation_fuel_consumption_kwh": "official_total_energy_demand",
    "official_total_energy_demand": "official_total_energy_demand",
    "domestic_share": "official_domestic_share",
    "international_share": "official_international_share",
    "emissions_total": "official_emissions_total",
}


@dataclass
class AviationCalibrationOutputs:
    calibration_targets: pd.DataFrame


@dataclass
class AviationCalibrationBuilder:
    def build(
        self,
        *,
        calibration_input_path: str | Path,
        enriched_stock_path: str | Path | None = None,
        output_path: str | Path = "data/processed/aviation/aviation_calibration_targets.csv",
    ) -> AviationCalibrationOutputs:
        raw = pd.read_csv(calibration_input_path)
        if raw.empty:
            raise ValueError(f"Calibration input file has no rows: {calibration_input_path}")
        normalized = raw.rename(columns=CALIBRATION_COLUMN_ALIASES).copy()
        if (
            "year" not in normalized.columns
            or "official_total_energy_demand" not in normalized.columns
        ):
            raise ValueError(
                "Calibration input must contain 'year' and 'official_total_energy_demand' columns.",
            )

        normalized["year"] = pd.to_numeric(normalized["year"], errors="coerce").astype("Int64")
        normalized["official_total_energy_demand"] = pd.to_numeric(
            normalized["official_total_energy_demand"],
            errors="coerce",
        )
        if "official_domestic_share" in normalized.columns:
            normalized["official_domestic_share"] = pd.to_numeric(
                normalized["official_domestic_share"],
                errors="coerce",
            )
        if "official_international_share" in normalized.columns:
            normalized["official_international_share"] = pd.to_numeric(
                normalized["official_international_share"],
                errors="coerce",
            )

        if enriched_stock_path is not None and Path(enriched_stock_path).exists():
            enriched = pd.read_csv(enriched_stock_path)
            german_flag = filter_german_flag_fleet(enriched)
            estimated_energy = (
                pd.to_numeric(
                    german_flag.get("baseline_energy_demand", pd.Series(dtype=float)),
                    errors="coerce",
                )
                .fillna(0.0)
                .sum()
            )
            normalized["estimated_energy_demand_german_flag"] = estimated_energy
            normalized["calibration_factor_german_flag"] = (
                normalized["official_total_energy_demand"] / estimated_energy
                if estimated_energy > 0.0
                else pd.NA
            )
        else:
            normalized["estimated_energy_demand_german_flag"] = pd.NA
            normalized["calibration_factor_german_flag"] = pd.NA

        destination = ensure_parent_dir(output_path)
        normalized.to_csv(destination, index=False)
        return AviationCalibrationOutputs(calibration_targets=normalized.reset_index(drop=True))
