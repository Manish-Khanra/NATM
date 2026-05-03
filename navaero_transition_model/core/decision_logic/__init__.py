from navaero_transition_model.core.decision_logic.ambiguity_aware_utility import (
    AmbiguityAwareCargoLogic,
    AmbiguityAwareMaritimeCargoLogic,
    AmbiguityAwareMaritimePassengerLogic,
    AmbiguityAwareUtilityLogic,
)
from navaero_transition_model.core.decision_logic.base import (
    AviationCargoDecisionLogic,
    AviationPassengerDecisionLogic,
    CandidateEvaluation,
    MaritimeCargoDecisionLogic,
    MaritimePassengerDecisionLogic,
    OperationMetrics,
    clamp,
    clean_scope_value,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityLogic,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility_cargo import (
    LegacyWeightedUtilityCargoLogic,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility_maritime_cargo import (
    LegacyWeightedUtilityMaritimeCargoLogic,
)

from .legacy_weighted_utility_maritime_passenger import (
    LegacyWeightedUtilityMaritimePassengerLogic,
)


def build_aviation_passenger_decision_logic(
    logic_name: str,
) -> AviationPassengerDecisionLogic:
    available_logics = {
        LegacyWeightedUtilityLogic.name: LegacyWeightedUtilityLogic,
        AmbiguityAwareUtilityLogic.name: AmbiguityAwareUtilityLogic,
    }
    try:
        return available_logics[logic_name]()
    except KeyError as exc:
        supported = ", ".join(sorted(available_logics))
        raise ValueError(
            f"Unsupported aviation investment_logic '{logic_name}'. Supported values: {supported}",
        ) from exc


def build_aviation_cargo_decision_logic(
    logic_name: str,
) -> AviationCargoDecisionLogic:
    available_logics = {
        LegacyWeightedUtilityCargoLogic.name: LegacyWeightedUtilityCargoLogic,
        AmbiguityAwareCargoLogic.name: AmbiguityAwareCargoLogic,
    }
    try:
        return available_logics[logic_name]()
    except KeyError as exc:
        supported = ", ".join(sorted(available_logics))
        raise ValueError(
            "Unsupported aviation cargo investment_logic "
            f"'{logic_name}'. Supported values: {supported}",
        ) from exc


def build_maritime_cargo_decision_logic(
    logic_name: str,
) -> MaritimeCargoDecisionLogic:
    available_logics = {
        LegacyWeightedUtilityMaritimeCargoLogic.name: LegacyWeightedUtilityMaritimeCargoLogic,
        AmbiguityAwareMaritimeCargoLogic.name: AmbiguityAwareMaritimeCargoLogic,
    }
    try:
        return available_logics[logic_name]()
    except KeyError as exc:
        supported = ", ".join(sorted(available_logics))
        raise ValueError(
            "Unsupported maritime cargo investment_logic "
            f"'{logic_name}'. Supported values: {supported}",
        ) from exc


def build_maritime_passenger_decision_logic(
    logic_name: str,
) -> MaritimePassengerDecisionLogic:
    available_logics = {
        LegacyWeightedUtilityMaritimePassengerLogic.name: (
            LegacyWeightedUtilityMaritimePassengerLogic
        ),
        AmbiguityAwareMaritimePassengerLogic.name: AmbiguityAwareMaritimePassengerLogic,
    }
    try:
        return available_logics[logic_name]()
    except KeyError as exc:
        supported = ", ".join(sorted(available_logics))
        raise ValueError(
            "Unsupported maritime passenger investment_logic "
            f"'{logic_name}'. Supported values: {supported}",
        ) from exc


__all__ = [
    "AviationCargoDecisionLogic",
    "AviationPassengerDecisionLogic",
    "AmbiguityAwareCargoLogic",
    "AmbiguityAwareMaritimeCargoLogic",
    "AmbiguityAwareMaritimePassengerLogic",
    "AmbiguityAwareUtilityLogic",
    "CandidateEvaluation",
    "LegacyWeightedUtilityMaritimeCargoLogic",
    "LegacyWeightedUtilityMaritimePassengerLogic",
    "LegacyWeightedUtilityCargoLogic",
    "LegacyWeightedUtilityLogic",
    "MaritimeCargoDecisionLogic",
    "MaritimePassengerDecisionLogic",
    "OperationMetrics",
    "build_aviation_cargo_decision_logic",
    "build_aviation_passenger_decision_logic",
    "build_maritime_cargo_decision_logic",
    "build_maritime_passenger_decision_logic",
    "clamp",
    "clean_scope_value",
]
