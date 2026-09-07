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


# EU ETS zero-rates emissions from a fuel's biomass/RFNBO/RCF/synthetic
# low-carbon content when it meets RED sustainability/GHG-savings criteria:
# aircraft/ship operators do not surrender allowances for that share, even
# though its true lifecycle emissions are nonzero (which technology_row's
# {primary,secondary}_energy_emission_factor still correctly reflects for
# reporting). Covers SAF (saf/hefa), e-kerosene (e_kerosene/ptl, an RFNBO),
# maritime biofuel (biofuel/fame), and renewable/green hydrogen used directly
# as a fuel (hydrogen, also an RFNBO when it meets RED criteria -- confirmed
# via Dutch Emissions Authority / EU Climate Action guidance: renewable
# hydrogen gets the same zero-rating as SAF/e-kerosene, not just when used as
# e-kerosene feedstock). Applies whichever carrier (primary or secondary) it
# appears as -- our hydrogen technologies use it as the primary carrier, but
# a blend where it's secondary would qualify identically. Fossil pilot fuels
# (LNG/methanol's small marine_diesel blend) and non-combustion carriers
# (battery/electricity, ~0 factor already) are not eligible and are left out.
ETS_ZERO_RATED_CARRIERS = frozenset({"saf", "e_kerosene", "biofuel", "hydrogen"})


def is_ets_zero_rated_secondary(technology_row: pd.Series) -> bool:
    carrier = clean_scope_value(technology_row.get("secondary_energy_carrier", "")).lower()
    return carrier in ETS_ZERO_RATED_CARRIERS


def is_ets_zero_rated_primary(technology_row: pd.Series) -> bool:
    carrier = clean_scope_value(technology_row.get("primary_energy_carrier", "")).lower()
    return carrier in ETS_ZERO_RATED_CARRIERS


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
