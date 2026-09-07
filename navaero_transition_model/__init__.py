"""NavAero Transition Model for aviation and maritime technology diffusion."""

import pandas as pd

from navaero_transition_model.core.agent_types import (
    AviationCargoAirlineAgent,
    AviationOperatorAgent,
    AviationPassengerAirlineAgent,
    BaseOperatorAgent,
    MaritimeOperatorAgent,
    TransportOperatorAgent,
)
from navaero_transition_model.core.case_inputs import (
    AviationCargoCaseData,
    AviationPassengerCaseData,
    ScenarioTable,
    TechnologyCatalog,
)
from navaero_transition_model.core.database import SQLiteSimulationStore
from navaero_transition_model.core.decision_logic import (
    AviationCargoDecisionLogic,
    AviationPassengerDecisionLogic,
    LegacyWeightedUtilityCargoLogic,
    LegacyWeightedUtilityLogic,
    build_aviation_cargo_decision_logic,
    build_aviation_passenger_decision_logic,
)
from navaero_transition_model.core.environment import TransitionEnvironment
from navaero_transition_model.core.fleet_management import Fleet
from navaero_transition_model.core.loaders import (
    AviationCargoCaseLoader,
    AviationCargoInputs,
    AviationPassengerCaseLoader,
    AviationPassengerInputs,
    load_aviation_cargo_case,
    load_aviation_cargo_fleet_stock,
    load_aviation_cargo_scenario,
    load_aviation_cargo_technology_catalog,
    load_aviation_passenger_case,
    load_aviation_passenger_fleet_stock,
    load_aviation_scenario,
    load_aviation_technology_catalog,
)
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.policy import PolicySettings, RampValue, SectorPolicySettings
from navaero_transition_model.core.result_exports import (
    AircraftStockExporter,
    AviationEnergyEmissionsExporter,
    AviationInvestmentExporter,
    AviationTechnologyExporter,
    DetailedOutputWriter,
)
from navaero_transition_model.core.scenario import (
    AviationPreprocessingConfig,
    NATMScenario,
    OpenAPPreprocessingConfig,
)

# pandas >=3.0 defaults every string/object column to an Arrow-backed
# ChunkedArray (`future.infer_string`). Fleet growth appends aircraft one row
# at a time via repeated `pd.concat` (see fleet.py's add_aircraft_from_template),
# and each single-row concat adds a new chunk to every string column's
# ChunkedArray rather than reallocating one contiguous buffer -- the columns
# get progressively more fragmented, which slows down not just later concats
# but every subsequent .loc/filter/map on those columns too. Benchmarked at
# ~185x slower (61s vs 0.33s for 3k single-row appends across 15 string
# columns) with Arrow-backed strings vs classic object dtype. Nothing in this
# codebase relies on Arrow-specific string semantics, so disable it globally.
pd.set_option("future.infer_string", False)

__all__ = [
    "AviationCargoAirlineAgent",
    "AviationCargoCaseData",
    "AviationCargoCaseLoader",
    "AviationCargoDecisionLogic",
    "AviationCargoInputs",
    "AviationOperatorAgent",
    "AviationPassengerAirlineAgent",
    "AviationPassengerCaseData",
    "AviationPassengerDecisionLogic",
    "AviationPassengerCaseLoader",
    "AviationPassengerInputs",
    "AviationPreprocessingConfig",
    "AircraftStockExporter",
    "AviationEnergyEmissionsExporter",
    "AviationInvestmentExporter",
    "AviationTechnologyExporter",
    "BaseOperatorAgent",
    "DetailedOutputWriter",
    "Fleet",
    "LegacyWeightedUtilityCargoLogic",
    "LegacyWeightedUtilityLogic",
    "MaritimeOperatorAgent",
    "NATMModel",
    "NATMScenario",
    "OpenAPPreprocessingConfig",
    "PolicySettings",
    "RampValue",
    "ScenarioTable",
    "SectorPolicySettings",
    "SQLiteSimulationStore",
    "TechnologyCatalog",
    "TransitionEnvironment",
    "TransportOperatorAgent",
    "build_aviation_cargo_decision_logic",
    "build_aviation_passenger_decision_logic",
    "load_aviation_cargo_case",
    "load_aviation_cargo_fleet_stock",
    "load_aviation_cargo_scenario",
    "load_aviation_cargo_technology_catalog",
    "load_aviation_passenger_case",
    "load_aviation_passenger_fleet_stock",
    "load_aviation_scenario",
    "load_aviation_technology_catalog",
]
