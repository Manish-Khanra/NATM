from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import (
    infer_is_german_flag,
    normalize_icao24,
    normalize_operator_name,
    normalize_registration,
    registration_prefix,
    safe_datetime_series,
    safe_numeric_series,
    snake_case_columns,
)

STOCK_SOURCE_COLUMN_ALIASES = {
    "id": "aircraft_id",
    "aircraft_type": "aircraft_type",
    "aircraft_type_icao": "aircraft_type",
    "operator": "operator_name",
    "operator_country": "operator_country",
    "status": "status",
    "build_date": "build_date",
    "build_country": "build_country",
    "first_customer_delivery_date": "first_customer_delivery_date",
    "delivery_date_operator": "delivery_date_operator",
    "exit_date_operator": "exit_date_operator",
    "nr_of_engines": "engine_count",
    "number_of_engines": "engine_count",
    "engine_manufacturer": "engine_manufacturer",
    "engine_type": "engine_type",
    "config_pax_con": "config_type",
    "seat_total": "seat_total",
    "haul": "haul",
    "range_km": "range_km",
    "age_years": "aircraft_age_years",
    "main_hub": "main_hub",
    "registration": "registration",
    "icao24": "icao24",
    "serial_number": "serial_number",
    "serialnumber": "serial_number",
    "built_year": "built_year",
}

STOCK_REQUIRED_COLUMNS = (
    "aircraft_id",
    "aircraft_type",
    "operator_name",
    "operator_country",
    "status",
    "build_date",
    "seat_total",
    "haul",
    "range_km",
    "aircraft_age_years",
    "main_hub",
)

STOCK_OPTIONAL_OUTPUT_COLUMNS = (
    "registration",
    "icao24",
    "serial_number",
    "registration_prefix",
    "build_year",
    "is_german_flag",
    "current_technology",
    "operator_economic_weight",
    "operator_environmental_weight",
    "free_ets_allocation",
    "peer_influence",
    "investment_logic",
    "annual_flights_base",
    "annual_distance_km_base",
    "domestic_activity_share_base",
    "international_activity_share_base",
    "mean_stage_length_km_base",
    "fuel_burn_per_year_base",
    "baseline_energy_demand",
    "airport_allocation_group",
    "main_hub_base",
    "match_confidence",
    "match_method",
    "activity_assignment_method",
)


def _read_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    dataframe = pd.read_csv(csv_path)
    if dataframe.empty:
        raise ValueError(f"CSV file has no rows: {csv_path}")
    return dataframe


@dataclass
class AviationStockCleaner:
    """Normalize aviation fleet stock into a consistent enrichment-ready table."""

    def clean(self, source: str | Path | pd.DataFrame) -> pd.DataFrame:
        if isinstance(source, pd.DataFrame):
            dataframe = source.copy()
        else:
            dataframe = _read_csv(source)

        normalized = snake_case_columns(dataframe).rename(columns=STOCK_SOURCE_COLUMN_ALIASES)
        missing = [column for column in STOCK_REQUIRED_COLUMNS if column not in normalized.columns]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"aviation fleet stock is missing required columns: {missing_text}")

        object_columns = normalized.select_dtypes(include=["object", "string"]).columns
        for column in object_columns:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()

        normalized["aircraft_id"] = safe_numeric_series(normalized["aircraft_id"]).astype("Int64")
        normalized["seat_total"] = safe_numeric_series(normalized["seat_total"])
        normalized["range_km"] = safe_numeric_series(normalized["range_km"])
        normalized["aircraft_age_years"] = safe_numeric_series(normalized["aircraft_age_years"])
        if "engine_count" in normalized.columns:
            normalized["engine_count"] = safe_numeric_series(normalized["engine_count"]).astype(
                "Int64",
            )
        if "build_year" in normalized.columns:
            normalized["build_year"] = safe_numeric_series(normalized["build_year"]).astype("Int64")

        normalized["build_date"] = safe_datetime_series(normalized["build_date"])
        if "build_year" not in normalized.columns:
            normalized["build_year"] = normalized["build_date"].dt.year.astype("Int64")
        else:
            normalized["build_year"] = normalized["build_year"].fillna(
                normalized["build_date"].dt.year.astype("Int64"),
            )

        normalized["segment"] = (
            normalized["haul"]
            .astype(str)
            .str.lower()
            .str.replace(
                "-haul",
                "",
                regex=False,
            )
        )
        if "registration" not in normalized.columns:
            normalized["registration"] = pd.Series("", index=normalized.index, dtype=object)
        if "icao24" not in normalized.columns:
            normalized["icao24"] = pd.Series("", index=normalized.index, dtype=object)
        if "serial_number" not in normalized.columns:
            normalized["serial_number"] = pd.Series("", index=normalized.index, dtype=object)
        normalized["registration"] = normalized["registration"].map(normalize_registration)
        normalized["icao24"] = normalized["icao24"].map(normalize_icao24)
        normalized["serial_number"] = normalized["serial_number"].astype(str).str.strip()
        normalized["registration_prefix"] = normalized["registration"].map(registration_prefix)
        normalized["is_german_flag"] = normalized["registration"].map(infer_is_german_flag)
        normalized["operator_name_normalized"] = normalized["operator_name"].map(
            normalize_operator_name,
        )
        normalized["status_normalized"] = normalized["status"].astype(str).str.lower().str.strip()
        normalized["aircraft_type_normalized"] = (
            normalized["aircraft_type"].astype(str).str.lower().str.replace(" ", "", regex=False)
        )

        for column in STOCK_OPTIONAL_OUTPUT_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA

        if "investment_logic" in normalized.columns:
            normalized["investment_logic"] = normalized["investment_logic"].replace("", pd.NA)
        normalized["investment_logic"] = normalized["investment_logic"].fillna(
            "legacy_weighted_utility",
        )
        normalized["operator_key"] = (
            normalized["operator_name"].astype(str).str.strip()
            + "::"
            + normalized["operator_country"].astype(str).str.strip()
        )
        return normalized.reset_index(drop=True)
