from __future__ import annotations

from pathlib import Path

import pandas as pd

from navaero_transition_model.core.case_inputs import (
    MaritimePassengerCaseData,
    ScenarioTable,
    TechnologyCatalog,
    normalize_maritime_passenger_fleet_stock,
)
from navaero_transition_model.core.loaders.base import CaseLoader

MaritimePassengerInputs = MaritimePassengerCaseData


class MaritimePassengerCaseLoader(CaseLoader):
    """Loader for maritime-passenger case files and derived case data."""

    fleet_filename = "maritime_fleet_stock.csv"
    technology_filename = "maritime_technology_catalog.csv"
    scenario_filename = "maritime_scenario.csv"

    def load_fleet_stock(self) -> pd.DataFrame:
        return load_maritime_passenger_fleet_stock(self.case_path / self.fleet_filename)

    def load_technology_catalog(self) -> pd.DataFrame:
        return load_maritime_passenger_technology_catalog(
            self.case_path / self.technology_filename,
        )

    def load_scenario(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return load_maritime_passenger_scenario(self.case_path / self.scenario_filename)

    def load_case(self) -> MaritimePassengerInputs:
        return MaritimePassengerCaseData.from_directory(self.case_path)


def load_maritime_passenger_fleet_stock(path: str | Path) -> pd.DataFrame:
    return normalize_maritime_passenger_fleet_stock(path)


def load_maritime_passenger_technology_catalog(path: str | Path) -> pd.DataFrame:
    return TechnologyCatalog.from_csv(path).to_frame()


def load_maritime_passenger_scenario(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    scenario_table = ScenarioTable.from_csv(path)
    return scenario_table.to_wide_frame(), scenario_table.to_long_frame()


def load_maritime_passenger_case(case_path: str | Path) -> MaritimePassengerInputs:
    return MaritimePassengerCaseLoader(case_path).load_case()
