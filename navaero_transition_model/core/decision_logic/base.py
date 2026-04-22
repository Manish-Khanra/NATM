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
