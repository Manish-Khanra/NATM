from __future__ import annotations

from pathlib import Path

import pandas as pd

TECHNOLOGY_REQUIRED_COLUMNS = (
    "technology_name",
    "primary_energy_carrier",
    "secondary_energy_carrier",
    "saf_pathway",
    "drop_in_fuel",
    "maximum_secondary_energy_share",
    "lifetime_years",
    "payback_interest_rate",
    "capex_eur",
    "maintenance_cost_share",
    "depreciation_cost_share",
    "kilometer_per_kwh",
    "trip_days_per_year",
    "fuel_capacity_kwh",
    "trip_length_km",
    "economy_seats",
    "business_seats",
    "first_class_seats",
    "mtow",
    "oew",
    "primary_energy_emission_factor",
    "secondary_energy_emission_factor",
    "hydrocarbon_factor",
    "carbon_monoxide_factor",
    "nitrogen_oxide_factor",
    "smoke_number_factor",
)

TECHNOLOGY_OPTIONAL_COLUMNS = (
    "segment",
    "payload_capacity_kg",
    "technology_family",
    "service_entry_year",
    "minimum_airport_class",
    "technology_notes",
    "openap_type",
    "reference_fuel_kg_per_km",
    "reference_energy_mwh_per_km",
    "reference_co2_kg_per_km",
    "fuel_estimation_source",
    "fuel_estimation_mode",
    "gross_tonnage",
    "net_tonnage_share",
    "max_tanker_size_tonnes",
    "reported_emission_factor",
    "carbondioxide_factor",
    "sulphur_factor",
    "minimum_port_class",
    "passenger_economy_class",
    "passenger_premium_class",
    "passenger_overnight_cabin",
    "passenger_business_class",
    "passenger_family_cabin",
    "cruise_interior_cabin",
    "cruise_oceanview_cabin",
    "cruise_balcony_cabin",
    "cruise_suite",
    "cruise_family_cabin",
    "cruise_single_cabin",
)


def _read_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    dataframe = pd.read_csv(csv_path)
    if dataframe.empty:
        raise ValueError(f"CSV file has no rows: {csv_path}")
    return dataframe


def _ensure_columns(
    dataframe: pd.DataFrame,
    required_columns: tuple[str, ...],
    label: str,
) -> None:
    missing = [column for column in required_columns if column not in dataframe.columns]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{label} is missing required columns: {missing_text}")


class TechnologyCatalog:
    def __init__(self, dataframe: pd.DataFrame) -> None:
        _ensure_columns(dataframe, TECHNOLOGY_REQUIRED_COLUMNS, "aviation technology catalog")
        normalized = dataframe.copy()
        for column in TECHNOLOGY_OPTIONAL_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA
        for column in normalized.select_dtypes(include=["object", "string"]).columns:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        if normalized["technology_name"].eq("").any():
            raise ValueError("aviation technology catalog contains blank technology_name values")
        duplicated = normalized.loc[
            normalized["technology_name"].duplicated(keep=False),
            "technology_name",
        ]
        if not duplicated.empty:
            duplicate_text = ", ".join(sorted(duplicated.unique()))
            raise ValueError(
                "aviation technology catalog requires unique technology_name values; "
                f"duplicates found: {duplicate_text}"
            )
        self._frame = normalized.reset_index(drop=True)

    @classmethod
    def from_csv(cls, path: str | Path) -> TechnologyCatalog:
        return cls(_read_csv(path))

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy()

    def candidates(self) -> pd.DataFrame:
        return self._frame.copy()

    def candidates_for_operation(
        self,
        *,
        segment: str | None = None,
        minimum_trip_length_km: float | None = None,
    ) -> pd.DataFrame:
        candidates = self._frame
        if minimum_trip_length_km is not None:
            trip_length = pd.to_numeric(candidates["trip_length_km"], errors="coerce")
            distance_filtered = candidates.loc[trip_length >= float(minimum_trip_length_km)]
            if not distance_filtered.empty:
                candidates = distance_filtered

        normalized_segment = (segment or "").strip().lower()
        if normalized_segment and "segment" in candidates.columns:
            segment_series = candidates["segment"].fillna("").astype(str).str.strip().str.lower()
            segment_filtered = candidates.loc[
                segment_series.eq("") | segment_series.eq(normalized_segment)
            ]
            if not segment_filtered.empty:
                candidates = segment_filtered

        return candidates.copy()

    def candidates_for_segment(self, segment: str) -> pd.DataFrame:
        return self.candidates_for_operation(segment=segment)

    def row_for(self, technology_name: str, segment: str | None = None) -> pd.Series:
        del segment
        candidates = self._frame.loc[self._frame["technology_name"] == technology_name]
        if candidates.empty:
            raise ValueError(f"Technology '{technology_name}' not found in aviation catalog")
        return candidates.iloc[0].copy()

    def is_conventional_row(self, technology_row: pd.Series) -> bool:
        technology_family = str(technology_row.get("technology_family", "")).strip().lower()
        if technology_family:
            return technology_family == "conventional"
        return str(technology_row["technology_name"]).startswith("kerosene")

    def is_conventional(self, technology_name: str, segment: str | None = None) -> bool:
        return self.is_conventional_row(self.row_for(technology_name, segment))

    def default_for_segment(self, segment: str) -> str:
        segment_catalog = self.candidates_for_operation(segment=segment)
        if segment_catalog.empty:
            segment_catalog = self._frame
        conventional = segment_catalog.loc[segment_catalog.apply(self.is_conventional_row, axis=1),]
        if not conventional.empty:
            return str(conventional.iloc[0]["technology_name"])
        return str(segment_catalog.iloc[0]["technology_name"])

    def default_for_operation(
        self,
        *,
        segment: str | None = None,
        minimum_trip_length_km: float | None = None,
    ) -> str:
        candidates = self.candidates_for_operation(
            segment=segment,
            minimum_trip_length_km=minimum_trip_length_km,
        )
        if candidates.empty:
            candidates = self._frame
        conventional = candidates.loc[candidates.apply(self.is_conventional_row, axis=1)]
        if not conventional.empty:
            return str(conventional.iloc[0]["technology_name"])
        return str(candidates.iloc[0]["technology_name"])
