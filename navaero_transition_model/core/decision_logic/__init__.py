from navaero_transition_model.core.decision_logic.base import (
    AviationCargoDecisionLogic,
    AviationPassengerDecisionLogic,
    CandidateEvaluation,
    MaritimeCargoDecisionLogic,
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


def build_aviation_passenger_decision_logic(
    logic_name: str,
) -> AviationPassengerDecisionLogic:
    available_logics = {
        LegacyWeightedUtilityLogic.name: LegacyWeightedUtilityLogic,
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
    }
    try:
        return available_logics[logic_name]()
    except KeyError as exc:
        supported = ", ".join(sorted(available_logics))
        raise ValueError(
            "Unsupported maritime cargo investment_logic "
            f"'{logic_name}'. Supported values: {supported}",
        ) from exc


__all__ = [
    "AviationCargoDecisionLogic",
    "AviationPassengerDecisionLogic",
    "CandidateEvaluation",
    "LegacyWeightedUtilityMaritimeCargoLogic",
    "LegacyWeightedUtilityCargoLogic",
    "LegacyWeightedUtilityLogic",
    "MaritimeCargoDecisionLogic",
    "OperationMetrics",
    "build_aviation_cargo_decision_logic",
    "build_aviation_passenger_decision_logic",
    "build_maritime_cargo_decision_logic",
    "clamp",
    "clean_scope_value",
]
