from __future__ import annotations

from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import snake_case_columns
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner
from navaero_transition_model.core.case_inputs.scenario_table import ScenarioTable
from navaero_transition_model.core.case_inputs.technology_catalog import TechnologyCatalog
from navaero_transition_model.core.decision_logic.base import DECISION_ATTITUDES

FLEET_COLUMN_ALIASES = {
    "ID": "aircraft_id",
    "Aircraft Type": "aircraft_type",
    "Operator": "operator_name",
    "Operator Country": "operator_country",
    "Status": "status",
    "Build Date": "build_date",
    "Build Country": "build_country",
    "First Customer Delivery Date": "first_customer_delivery_date",
    "Delivery Date Operator": "delivery_date_operator",
    "Exit Date Operator": "exit_date_operator",
    "Nr. of Engines": "engine_count",
    "Engine Manufacturer": "engine_manufacturer",
    "Engine Type": "engine_type",
    "Config (Pax/Con)": "config_type",
    "Seat Total": "seat_total",
    "Haul": "haul",
    "Range (km)": "range_km",
    "Age (Years)": "aircraft_age_years",
    "Main Hub": "main_hub",
}

FLEET_REQUIRED_COLUMNS = (
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

EMPIRICAL_ACTIVITY_COLUMNS = (
    "registration",
    "icao24",
    "serial_number",
    "is_german_flag",
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
    "openap_type",
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
)

POSITIVE_ACTIVITY_COLUMNS = (
    "annual_flights_base",
    "annual_distance_km_base",
    "mean_stage_length_km_base",
    "fuel_burn_per_year_base",
    "baseline_energy_demand",
    "number_of_trips",
    "total_distance_km",
    "total_fuel_kg",
    "total_energy_mwh",
    "total_co2_kg",
    "fuel_kg_per_km",
    "energy_mwh_per_km",
    "co2_kg_per_km",
    "average_flight_distance_km",
    "average_fuel_kg_per_flight",
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


def normalize_aviation_cargo_fleet_stock(path: str | Path) -> pd.DataFrame:
    normalized = AviationStockCleaner().clean(path)
    _ensure_columns(normalized, FLEET_REQUIRED_COLUMNS, "aviation fleet stock")
    normalized["is_cargo"] = normalized.get("config_type", "Con").astype(str).str.lower().eq("con")
    if "investment_logic" not in normalized.columns:
        normalized["investment_logic"] = "legacy_weighted_utility_cargo"
    else:
        normalized["investment_logic"] = (
            normalized["investment_logic"]
            .replace("", pd.NA)
            .fillna("legacy_weighted_utility_cargo")
        )
    if "decision_attitude" not in normalized.columns:
        normalized["decision_attitude"] = "risk_neutral"
    else:
        normalized["decision_attitude"] = (
            normalized["decision_attitude"].replace("", pd.NA).fillna("risk_neutral")
        )
    normalized["decision_attitude"] = (
        normalized["decision_attitude"].astype(str).str.strip().str.lower()
    )
    unsupported_attitudes = set(normalized["decision_attitude"].astype(str)) - set(
        DECISION_ATTITUDES,
    )
    if unsupported_attitudes:
        supported = ", ".join(DECISION_ATTITUDES)
        unsupported = ", ".join(sorted(unsupported_attitudes))
        raise ValueError(
            f"Unsupported aviation cargo decision_attitude values: {unsupported}. "
            f"Supported values: {supported}",
        )
    normalized["operator_key"] = (
        normalized["operator_name"].astype(str).str.strip()
        + "::"
        + normalized["operator_country"].astype(str).str.strip()
    )
    return normalized.reset_index(drop=True)


def _load_optional_activity_profiles(path: str | Path) -> pd.DataFrame:
    activity_path = Path(path)
    if not activity_path.exists():
        return pd.DataFrame()
    dataframe = pd.read_csv(activity_path)
    if dataframe.empty:
        return pd.DataFrame()
    normalized = snake_case_columns(dataframe)
    for column in normalized.select_dtypes(include=["object", "string"]).columns:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    return normalized.reset_index(drop=True)


def _merge_optional_activity_profiles(
    fleet_frame: pd.DataFrame,
    activity_profiles: pd.DataFrame,
) -> pd.DataFrame:
    if activity_profiles.empty:
        return fleet_frame

    merged = fleet_frame.copy()
    available_activity_columns = [
        column for column in EMPIRICAL_ACTIVITY_COLUMNS if column in activity_profiles.columns
    ]
    if not available_activity_columns:
        return merged
    for column in available_activity_columns:
        if column not in merged.columns:
            merged[column] = pd.NA

    def _missing_activity_mask(column: str) -> pd.Series:
        missing_mask = merged[column].isna()
        if column in POSITIVE_ACTIVITY_COLUMNS:
            numeric = pd.to_numeric(merged[column], errors="coerce")
            missing_mask = missing_mask | numeric.isna() | numeric.le(0.0)
        return missing_mask

    def _valid_profile_rows(source: pd.DataFrame, column: str) -> pd.DataFrame:
        candidates = source.dropna(subset=[column]).copy()
        if column in POSITIVE_ACTIVITY_COLUMNS:
            numeric = pd.to_numeric(candidates[column], errors="coerce")
            candidates = candidates.loc[numeric > 0.0]
        return candidates

    if "aircraft_id" in activity_profiles.columns:
        profile_by_id = activity_profiles[
            ["aircraft_id"] + available_activity_columns
        ].drop_duplicates(
            subset=["aircraft_id"],
            keep="first",
        )
        merged = merged.merge(
            profile_by_id, on="aircraft_id", how="left", suffixes=("", "_profile")
        )
        for column in available_activity_columns:
            profile_column = f"{column}_profile"
            if profile_column in merged.columns:
                missing_mask = _missing_activity_mask(column)
                merged.loc[missing_mask, column] = merged.loc[missing_mask, profile_column]
                merged = merged.drop(columns=profile_column)

    def _fill_from_key(key_column: str) -> None:
        if key_column not in merged.columns or key_column not in activity_profiles.columns:
            return
        profile_lookup = (
            activity_profiles.loc[
                activity_profiles[key_column].astype(str).str.strip() != "",
                [key_column] + available_activity_columns,
            ]
            .drop_duplicates(subset=[key_column], keep="first")
            .set_index(key_column)
        )
        for column in available_activity_columns:
            missing_mask = _missing_activity_mask(column)
            if not missing_mask.any():
                continue
            merged.loc[missing_mask, column] = merged.loc[missing_mask, key_column].map(
                profile_lookup[column],
            )

    _fill_from_key("registration")
    _fill_from_key("icao24")

    if "aircraft_type" in activity_profiles.columns:
        for column in available_activity_columns:
            missing_mask = _missing_activity_mask(column)
            if not missing_mask.any():
                continue
            type_source = _valid_profile_rows(activity_profiles, column)
            type_defaults = (
                type_source.loc[
                    type_source["aircraft_type"].astype(str).str.strip() != "",
                    ["aircraft_type", column],
                ]
                .groupby("aircraft_type", dropna=False)[column]
                .first()
            )
            merged.loc[missing_mask, column] = merged.loc[missing_mask, "aircraft_type"].map(
                type_defaults,
            )

    if "segment" in activity_profiles.columns:
        segment_source = activity_profiles.copy()
        if "activity_assignment_method" in segment_source.columns:
            segment_methods = {
                "segment",
                "segment_default",
                "segment_fallback",
                "openap_segment",
            }
            segment_source = segment_source.loc[
                segment_source["activity_assignment_method"]
                .astype(str)
                .str.strip()
                .str.lower()
                .isin(segment_methods)
            ]
        for column in available_activity_columns:
            missing_mask = _missing_activity_mask(column)
            if not missing_mask.any():
                continue
            valid_segment_source = _valid_profile_rows(segment_source, column)
            segment_defaults = (
                valid_segment_source.loc[
                    valid_segment_source["segment"].astype(str).str.strip() != "",
                    ["segment", column],
                ]
                .groupby("segment", dropna=False)[column]
                .first()
            )
            merged.loc[missing_mask, column] = merged.loc[missing_mask, "segment"].map(
                segment_defaults,
            )

    return merged.reset_index(drop=True)


class AviationCargoCaseData:
    def __init__(
        self,
        *,
        fleet_frame: pd.DataFrame,
        technology_catalog: TechnologyCatalog,
        scenario_table: ScenarioTable,
        activity_profiles_frame: pd.DataFrame | None = None,
        case_dir: Path | None = None,
    ) -> None:
        self.case_dir = case_dir
        self.fleet_frame = fleet_frame.reset_index(drop=True).copy()
        self.technology_catalog = technology_catalog
        self.scenario_table = scenario_table
        self.activity_profiles_frame = (
            pd.DataFrame() if activity_profiles_frame is None else activity_profiles_frame.copy()
        )

    @classmethod
    def from_directory(cls, case_path: str | Path) -> AviationCargoCaseData:
        case_dir = Path(case_path)
        fleet_frame = normalize_aviation_cargo_fleet_stock(
            case_dir / "aviation_fleet_stock.csv",
        )
        activity_profiles_frame = _load_optional_activity_profiles(
            case_dir / "aviation_activity_profiles.csv",
        )
        fleet_frame = _merge_optional_activity_profiles(fleet_frame, activity_profiles_frame)
        technology_catalog = TechnologyCatalog.from_csv(
            case_dir / "aviation_technology_catalog.csv",
        )
        scenario_table = ScenarioTable.from_csv(case_dir / "aviation_scenario.csv")
        return cls(
            fleet_frame=fleet_frame,
            technology_catalog=technology_catalog,
            scenario_table=scenario_table,
            activity_profiles_frame=activity_profiles_frame,
            case_dir=case_dir,
        )

    @property
    def fleet(self) -> pd.DataFrame:
        return self.fleet_frame.copy()

    @property
    def scenario_wide(self) -> pd.DataFrame:
        return self.scenario_table.to_wide_frame()

    @property
    def scenario_long(self) -> pd.DataFrame:
        return self.scenario_table.to_long_frame()

    @property
    def activity_profiles(self) -> pd.DataFrame:
        return self.activity_profiles_frame.copy()

    def grouped_operator_fleet(self):
        return self.fleet_frame.groupby(["operator_name", "operator_country"], sort=True)

    def validate_capacity_planning_inputs(self, start_year: int, end_year: int) -> None:
        scenario_table = self.scenario_table
        if not scenario_table.has_rows("freight_tonne_km_demand"):
            raise ValueError(
                "aviation cargo scenario CSV must include 'freight_tonne_km_demand' rows "
                "for aviation cargo capacity planning.",
            )
        if not scenario_table.has_rows("operator_market_share"):
            raise ValueError(
                "aviation cargo scenario CSV must include 'operator_market_share' rows "
                "for aviation cargo capacity planning.",
            )
        if "payload_capacity_kg" not in self.technology_catalog.to_frame().columns:
            raise ValueError(
                "aviation cargo technology catalog must include 'payload_capacity_kg'.",
            )

        years = range(int(start_year), int(end_year) + 1)
        fleet_scope = (
            self.fleet_frame.loc[self.fleet_frame["is_cargo"]]
            .drop_duplicates(subset=["operator_name", "operator_country", "segment"])
            .loc[:, ["operator_name", "operator_country", "segment"]]
        )
        demand_scope = fleet_scope.drop_duplicates(subset=["operator_country", "segment"]).loc[
            :, ["operator_country", "segment"]
        ]

        missing_demand: list[str] = []
        for year in years:
            for row in demand_scope.itertuples(index=False):
                if (
                    scenario_table.value(
                        "freight_tonne_km_demand",
                        year,
                        country=row.operator_country,
                        segment=row.segment,
                        default=None,
                    )
                    is None
                ):
                    missing_demand.append(
                        f"{year}:{row.operator_country}/{row.segment}",
                    )

        missing_share: list[str] = []
        for year in years:
            for row in fleet_scope.itertuples(index=False):
                if (
                    scenario_table.value(
                        "operator_market_share",
                        year,
                        country=row.operator_country,
                        operator_name=row.operator_name,
                        segment=row.segment,
                        default=None,
                    )
                    is None
                ):
                    missing_share.append(
                        f"{year}:{row.operator_name}/{row.operator_country}/{row.segment}",
                    )

        if missing_demand:
            sample = ", ".join(missing_demand[:5])
            raise ValueError(
                "aviation cargo scenario CSV is missing 'freight_tonne_km_demand' values for "
                f"required country/segment/year combinations. Examples: {sample}",
            )
        if missing_share:
            sample = ", ".join(missing_share[:5])
            raise ValueError(
                "aviation cargo scenario CSV is missing 'operator_market_share' values for "
                f"required operator/country/segment/year combinations. Examples: {sample}",
            )
