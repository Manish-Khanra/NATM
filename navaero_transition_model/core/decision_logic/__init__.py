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
    LegacyWeightedUtilityCargoLogic,
    LegacyWeightedUtilityLogic,
    LegacyWeightedUtilityMaritimeCargoLogic,
    LegacyWeightedUtilityMaritimePassengerLogic,
)

LEGACY_WEIGHTED_UTILITY_CARGO_ALIAS = "legacy_weighted_utility_cargo"
LEGACY_WEIGHTED_UTILITY_MARITIME_CARGO_ALIAS = "legacy_weighted_utility_maritime_cargo"
LEGACY_WEIGHTED_UTILITY_MARITIME_PASSENGER_ALIAS = "legacy_weighted_utility_maritime_passenger"
AMBIGUITY_AWARE_UTILITY_CARGO_ALIAS = "ambiguity_aware_utility_cargo"
AMBIGUITY_AWARE_UTILITY_MARITIME_CARGO_ALIAS = "ambiguity_aware_utility_maritime_cargo"
AMBIGUITY_AWARE_UTILITY_MARITIME_PASSENGER_ALIAS = "ambiguity_aware_utility_maritime_passenger"


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
        LegacyWeightedUtilityLogic.name: LegacyWeightedUtilityCargoLogic,
        LEGACY_WEIGHTED_UTILITY_CARGO_ALIAS: LegacyWeightedUtilityCargoLogic,
        AmbiguityAwareCargoLogic.name: AmbiguityAwareCargoLogic,
        AMBIGUITY_AWARE_UTILITY_CARGO_ALIAS: AmbiguityAwareCargoLogic,
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
        LegacyWeightedUtilityLogic.name: LegacyWeightedUtilityMaritimeCargoLogic,
        LEGACY_WEIGHTED_UTILITY_MARITIME_CARGO_ALIAS: LegacyWeightedUtilityMaritimeCargoLogic,
        AmbiguityAwareMaritimeCargoLogic.name: AmbiguityAwareMaritimeCargoLogic,
        AMBIGUITY_AWARE_UTILITY_MARITIME_CARGO_ALIAS: AmbiguityAwareMaritimeCargoLogic,
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
        LegacyWeightedUtilityLogic.name: LegacyWeightedUtilityMaritimePassengerLogic,
        LEGACY_WEIGHTED_UTILITY_MARITIME_PASSENGER_ALIAS: (
            LegacyWeightedUtilityMaritimePassengerLogic
        ),
        AmbiguityAwareMaritimePassengerLogic.name: AmbiguityAwareMaritimePassengerLogic,
        AMBIGUITY_AWARE_UTILITY_MARITIME_PASSENGER_ALIAS: (AmbiguityAwareMaritimePassengerLogic),
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
