from __future__ import annotations

from pathlib import Path

import pandas as pd

from natm.core.case_data import (
    AviationPassengerCaseData,
    ScenarioTable,
    TechnologyCatalog,
    normalize_aviation_fleet_stock,
)

AviationPassengerInputs = AviationPassengerCaseData


def load_aviation_passenger_fleet_stock(path: str | Path) -> pd.DataFrame:
    return normalize_aviation_fleet_stock(path)


def load_aviation_technology_catalog(path: str | Path) -> pd.DataFrame:
    return TechnologyCatalog.from_csv(path).to_frame()


def load_aviation_scenario(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    scenario_table = ScenarioTable.from_csv(path)
    return scenario_table.to_wide_frame(), scenario_table.to_long_frame()


def load_aviation_passenger_case(case_path: str | Path) -> AviationPassengerInputs:
    return AviationPassengerCaseData.from_directory(case_path)
