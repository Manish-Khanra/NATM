from __future__ import annotations

from pathlib import Path

import pandas as pd

from navaero_transition_model.core.case_inputs.scenario_table import ScenarioTable
from navaero_transition_model.core.case_inputs.technology_catalog import TechnologyCatalog
from navaero_transition_model.core.decision_logic.base import DECISION_ATTITUDES

FLEET_COLUMN_ALIASES = {
    "ID": "aircraft_id",
    "Vessel ID": "aircraft_id",
    "Vessel Type": "aircraft_type",
    "Operator": "operator_name",
    "Operator Country": "operator_country",
    "Status": "status",
    "Build Date": "build_date",
    "Build Country": "build_country",
    "Delivery Date Operator": "delivery_date_operator",
    "Exit Date Operator": "exit_date_operator",
    "Segment": "segment",
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
    "segment",
    "range_km",
    "aircraft_age_years",
    "main_hub",
)

PASSENGER_CAPACITY_COLUMNS = (
    "passenger_economy_class",
    "passenger_premium_class",
    "passenger_overnight_cabin",
    "passenger_business_class",
    "passenger_family_cabin",
    "economy_seats",
    "business_seats",
    "first_class_seats",
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


def normalize_maritime_passenger_fleet_stock(path: str | Path) -> pd.DataFrame:
    dataframe = _read_csv(path).rename(columns=FLEET_COLUMN_ALIASES)
    _ensure_columns(dataframe, FLEET_REQUIRED_COLUMNS, "maritime passenger fleet stock")

    normalized = dataframe.copy()
    for column in normalized.select_dtypes(include=["object", "string"]).columns:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    normalized["segment"] = normalized["segment"].astype(str).str.strip().str.lower()
    normalized["vessel_id"] = normalized["aircraft_id"]
    normalized["vessel_type"] = normalized["aircraft_type"]
    normalized["vessel_age_years"] = normalized["aircraft_age_years"]
    normalized["is_passenger"] = True
    if "investment_logic" not in normalized.columns:
        normalized["investment_logic"] = "legacy_weighted_utility_maritime_passenger"
    else:
        normalized["investment_logic"] = (
            normalized["investment_logic"]
            .replace("", pd.NA)
            .fillna("legacy_weighted_utility_maritime_passenger")
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
            f"Unsupported maritime passenger decision_attitude values: {unsupported}. "
            f"Supported values: {supported}",
        )
    normalized["operator_key"] = (
        normalized["operator_name"].astype(str).str.strip()
        + "::"
        + normalized["operator_country"].astype(str).str.strip()
    )
    return normalized.reset_index(drop=True)


class MaritimePassengerCaseData:
    def __init__(
        self,
        *,
        fleet_frame: pd.DataFrame,
        technology_catalog: TechnologyCatalog,
        scenario_table: ScenarioTable,
        case_dir: Path | None = None,
    ) -> None:
        self.case_dir = case_dir
        self.fleet_frame = fleet_frame.reset_index(drop=True).copy()
        self.technology_catalog = technology_catalog
        self.scenario_table = scenario_table

    @classmethod
    def from_directory(cls, case_path: str | Path) -> MaritimePassengerCaseData:
        case_dir = Path(case_path)
        fleet_frame = normalize_maritime_passenger_fleet_stock(
            case_dir / "maritime_fleet_stock.csv",
        )
        technology_catalog = TechnologyCatalog.from_csv(
            case_dir / "maritime_technology_catalog.csv",
        )
        scenario_table = ScenarioTable.from_csv(case_dir / "maritime_scenario.csv")
        return cls(
            fleet_frame=fleet_frame,
            technology_catalog=technology_catalog,
            scenario_table=scenario_table,
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

    def grouped_operator_fleet(self):
        return self.fleet_frame.groupby(["operator_name", "operator_country"], sort=True)

    def validate_capacity_planning_inputs(self, start_year: int, end_year: int) -> None:
        scenario_table = self.scenario_table
        if not scenario_table.has_rows("passenger_km_demand"):
            raise ValueError(
                "maritime passenger scenario CSV must include 'passenger_km_demand' rows "
                "for maritime passenger capacity planning.",
            )
        if not scenario_table.has_rows("operator_market_share"):
            raise ValueError(
                "maritime passenger scenario CSV must include 'operator_market_share' rows "
                "for maritime passenger capacity planning.",
            )

        technology_frame = self.technology_catalog.to_frame()
        present_capacity_columns = [
            column for column in PASSENGER_CAPACITY_COLUMNS if column in technology_frame.columns
        ]
        if not present_capacity_columns:
            raise ValueError(
                "maritime passenger technology catalog must include passenger-capacity columns.",
            )
        capacity_total = pd.to_numeric(
            technology_frame[present_capacity_columns].fillna(0.0).sum(axis=1),
            errors="coerce",
        )
        if float(capacity_total.max()) <= 0.0:
            raise ValueError(
                "maritime passenger technology catalog must define positive passenger capacity "
                "in at least one cabin or seat column.",
            )

        years = range(int(start_year), int(end_year) + 1)
        fleet_scope = self.fleet_frame.drop_duplicates(
            subset=["operator_name", "operator_country", "segment"],
        ).loc[:, ["operator_name", "operator_country", "segment"]]
        demand_scope = fleet_scope.drop_duplicates(subset=["operator_country", "segment"]).loc[
            :, ["operator_country", "segment"]
        ]

        missing_demand: list[str] = []
        for year in years:
            for row in demand_scope.itertuples(index=False):
                if (
                    scenario_table.value(
                        "passenger_km_demand",
                        year,
                        country=row.operator_country,
                        segment=row.segment,
                        default=None,
                    )
                    is None
                ):
                    missing_demand.append(f"{year}:{row.operator_country}/{row.segment}")

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
                "maritime passenger scenario CSV is missing 'passenger_km_demand' values for "
                f"required country/segment/year combinations. Examples: {sample}",
            )
        if missing_share:
            sample = ", ".join(missing_share[:5])
            raise ValueError(
                "maritime passenger scenario CSV is missing 'operator_market_share' values for "
                f"required operator/country/segment/year combinations. Examples: {sample}",
            )
