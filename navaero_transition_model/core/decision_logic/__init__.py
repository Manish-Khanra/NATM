from navaero_transition_model.core.decision_logic.base import (
    AviationPassengerDecisionLogic,
    CandidateEvaluation,
    OperationMetrics,
    clamp,
    clean_scope_value,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityLogic,
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


__all__ = [
    "AviationPassengerDecisionLogic",
    "CandidateEvaluation",
    "LegacyWeightedUtilityLogic",
    "OperationMetrics",
    "build_aviation_passenger_decision_logic",
    "clamp",
    "clean_scope_value",
]
