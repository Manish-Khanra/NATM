from __future__ import annotations

from pathlib import Path

import pandas as pd

TECHNOLOGY_REQUIRED_COLUMNS = (
    "technology_name",
    "segment",
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
    "payload_capacity_kg",
    "technology_family",
    "service_entry_year",
    "minimum_airport_class",
    "technology_notes",
    "gross_tonnage",
    "net_tonnage_share",
    "max_tanker_size_tonnes",
    "reported_emission_factor",
    "carbondioxide_factor",
    "sulphur_factor",
    "minimum_port_class",
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
        self._frame = normalized.reset_index(drop=True)

    @classmethod
    def from_csv(cls, path: str | Path) -> TechnologyCatalog:
        return cls(_read_csv(path))

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy()

    def candidates_for_segment(self, segment: str) -> pd.DataFrame:
        return self._frame.loc[self._frame["segment"] == segment].copy()

    def row_for(self, technology_name: str, segment: str | None = None) -> pd.Series:
        candidates = self._frame.loc[self._frame["technology_name"] == technology_name]
        if segment is not None:
            segment_candidates = candidates.loc[candidates["segment"] == segment]
            if not segment_candidates.empty:
                candidates = segment_candidates
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
        segment_catalog = self.candidates_for_segment(segment)
        if segment_catalog.empty:
            raise ValueError(f"No technology options found for segment '{segment}'")

        conventional = segment_catalog.loc[segment_catalog.apply(self.is_conventional_row, axis=1),]
        if not conventional.empty:
            return str(conventional.iloc[0]["technology_name"])
        return str(segment_catalog.iloc[0]["technology_name"])
