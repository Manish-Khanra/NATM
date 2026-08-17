from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import pandas as pd

if TYPE_CHECKING:
    from navaero_transition_model.core.agent_types.aviation_cargo_airline import (
        AviationCargoAirlineAgent,
    )
    from navaero_transition_model.core.agent_types.aviation_passenger_airline import (
        AviationPassengerAirlineAgent,
    )
    from navaero_transition_model.core.agent_types.maritime_cargo_shipline import (
        MaritimeCargoShiplineAgent,
    )
    from navaero_transition_model.core.agent_types.maritime_passenger_shipline import (
        MaritimePassengerShiplineAgent,
    )


ACTIVE_DECISION_ATTITUDES = (
    "risk_neutral",
    "risk_averse_mean",
    "risk_averse_expected_shortfall",
    "minimax_regret",
)
# The precise NPV-selection rule vocabulary. Same values as
# ACTIVE_DECISION_ATTITUDES; aliased under this name for readability at the
# `decision_mode` column call sites, which are a separate concept from
# `decision_attitude` even though they currently share a value set.
DECISION_MODES = ACTIVE_DECISION_ATTITUDES
# Coarse `decision_attitude` behavioral labels (risk_averse, ambiguity_averse)
# map to this default `decision_mode` when a fleet row leaves decision_mode
# blank. Both labels default to the same mode today; they remain distinct,
# permanent labels a case can use to tell two similarly-cautious operators
# apart in output even when they resolve to the same underlying rule.
DECISION_ATTITUDE_DEFAULT_MODE = {
    "risk_averse": "risk_averse_expected_shortfall",
    "ambiguity_averse": "risk_averse_expected_shortfall",
}
DECISION_ATTITUDES = (
    *ACTIVE_DECISION_ATTITUDES,
    *DECISION_ATTITUDE_DEFAULT_MODE,
)


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def clean_scope_value(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class CandidateEvaluation:
    technology_name: str
    total_utility: float
    economic_utility: float
    environmental_utility: float
    payback_year: int
    total_emission: float
    primary_energy_quantity: float
    secondary_energy_quantity: float
    chargeable_emission: float
    remaining_ets_allowance: float
    current_year_operating_cost: float
    effective_conventional_cost: float
    effective_alternative_cost: float
    net_present_value: float


@dataclass(frozen=True)
class OperationMetrics:
    total_cost: float
    total_emission: float
    primary_energy_quantity: float
    secondary_energy_quantity: float
    chargeable_emission: float
    remaining_ets_allowance: float


class AviationPassengerDecisionLogic(Protocol):
    name: str

    def step(self, agent: AviationPassengerAirlineAgent, year: int) -> None: ...

    def annual_operation_metrics(
        self,
        agent: AviationPassengerAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics: ...


class AviationCargoDecisionLogic(Protocol):
    name: str

    def step(self, agent: AviationCargoAirlineAgent, year: int) -> None: ...

    def annual_operation_metrics(
        self,
        agent: AviationCargoAirlineAgent,
        aircraft: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics: ...


class MaritimeCargoDecisionLogic(Protocol):
    name: str

    def step(self, agent: MaritimeCargoShiplineAgent, year: int) -> None: ...

    def annual_operation_metrics(
        self,
        agent: MaritimeCargoShiplineAgent,
        vessel: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics: ...


class MaritimePassengerDecisionLogic(Protocol):
    name: str

    def step(self, agent: MaritimePassengerShiplineAgent, year: int) -> None: ...

    def annual_operation_metrics(
        self,
        agent: MaritimePassengerShiplineAgent,
        vessel: pd.Series,
        technology_row: pd.Series,
        year: int,
        free_ets_balance: float | None = None,
    ) -> OperationMetrics: ...
