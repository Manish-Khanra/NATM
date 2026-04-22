from navaero_transition_model.core.decision_logic.base import (
    AviationCargoDecisionLogic,
    AviationPassengerDecisionLogic,
    CandidateEvaluation,
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


__all__ = [
    "AviationCargoDecisionLogic",
    "AviationPassengerDecisionLogic",
    "CandidateEvaluation",
    "LegacyWeightedUtilityCargoLogic",
    "LegacyWeightedUtilityLogic",
    "OperationMetrics",
    "build_aviation_cargo_decision_logic",
    "build_aviation_passenger_decision_logic",
    "clamp",
    "clean_scope_value",
]
