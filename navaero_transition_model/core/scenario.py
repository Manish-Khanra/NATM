from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class OpenAPPreprocessingConfig:
    estimate_fuel: bool = False
    mode: str = "synthetic"
    route_extension_factor: float = 1.05
    include_non_co2: bool = True

    @classmethod
    def from_dict(cls, payload: dict | None) -> OpenAPPreprocessingConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("preprocessing.aviation.openap must be a mapping")
        return cls(
            estimate_fuel=bool(payload.get("estimate_fuel", False)),
            mode=str(payload.get("mode", "synthetic")),
            route_extension_factor=float(payload.get("route_extension_factor", 1.05)),
            include_non_co2=bool(payload.get("include_non_co2", True)),
        )


@dataclass(frozen=True)
class AviationPreprocessingConfig:
    enabled: bool = False
    stock_input: str | None = None
    opensky_raw: str | None = None
    flightlist_folder: str | None = None
    airport_metadata: str | None = None
    technology_catalog: str | None = None
    calibration_input: str | None = None
    processed_dir: str | None = None
    openap: OpenAPPreprocessingConfig = field(default_factory=OpenAPPreprocessingConfig)

    @classmethod
    def from_dict(cls, payload: dict | None) -> AviationPreprocessingConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("preprocessing.aviation must be a mapping")
        return cls(
            enabled=bool(payload.get("enabled", False)),
            stock_input=_optional_text(payload.get("stock_input")),
            opensky_raw=_optional_text(payload.get("opensky_raw")),
            flightlist_folder=_optional_text(payload.get("flightlist_folder")),
            airport_metadata=_optional_text(payload.get("airport_metadata")),
            technology_catalog=_optional_text(payload.get("technology_catalog")),
            calibration_input=_optional_text(payload.get("calibration_input")),
            processed_dir=_optional_text(payload.get("processed_dir")),
            openap=OpenAPPreprocessingConfig.from_dict(payload.get("openap")),
        )

    def resolve_path(self, base_path: Path, field_name: str) -> Path | None:
        value = getattr(self, field_name)
        if value is None:
            return None
        return (base_path / value).resolve()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class AmbiguityAwareDecisionConfig:
    enabled: bool = False
    scenario_ids: tuple[str, ...] = ("baseline",)
    probabilities: dict[str, float] = field(default_factory=lambda: {"baseline": 1.0})
    ambiguity_enabled: bool = False
    probability_deviation: float = 0.0
    expected_shortfall_alpha: float = 0.2
    robust_metric: str = "worst_case_expected_shortfall"
    risk_metric: str | None = None
    probability_table: str | None = None
    belief_sets: tuple[str, ...] = ()
    probability_input_format: str = "auto"
    tail_alpha: float = 0.95
    probability_tolerance: float = 1e-8
    write_debug_outputs: bool = True
    risk_neutral_belief_set: str | None = None

    @classmethod
    def from_dict(cls, payload: dict | None) -> AmbiguityAwareDecisionConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("ambiguity_aware_decision must be a mapping")
        enabled = bool(payload.get("enabled", False))
        if not enabled:
            return cls(enabled=False)

        scenario_ids = tuple(
            str(item).strip() for item in payload.get("scenario_ids", ()) if str(item).strip()
        )
        raw_probabilities = payload.get("probabilities")
        if raw_probabilities is None:
            probabilities = {scenario_id: 1.0 / len(scenario_ids) for scenario_id in scenario_ids}
        else:
            if not isinstance(raw_probabilities, dict):
                raise ValueError("ambiguity_aware_decision.probabilities must be a mapping")
            if not scenario_ids:
                scenario_ids = tuple(
                    str(scenario_id).strip()
                    for scenario_id in raw_probabilities
                    if str(scenario_id).strip()
                )
            missing = [
                scenario_id for scenario_id in scenario_ids if scenario_id not in raw_probabilities
            ]
            if missing:
                missing_text = ", ".join(missing)
                raise ValueError(
                    "ambiguity_aware_decision.probabilities is missing entries for: "
                    f"{missing_text}",
                )
            probabilities = {
                scenario_id: float(raw_probabilities[scenario_id]) for scenario_id in scenario_ids
            }
            total_probability = sum(probabilities.values())
            if total_probability <= 0.0:
                raise ValueError(
                    "ambiguity_aware_decision probabilities must sum to a positive value",
                )
            if abs(total_probability - 1.0) > 1e-9:
                warnings.warn(
                    "ambiguity_aware_decision probabilities do not sum to 1.0; normalizing.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                probabilities = {
                    scenario_id: value / total_probability
                    for scenario_id, value in probabilities.items()
                }

        ambiguity_payload = payload.get("ambiguity") or {}
        if not isinstance(ambiguity_payload, dict):
            raise ValueError("ambiguity_aware_decision.ambiguity must be a mapping")
        probability_deviation = float(ambiguity_payload.get("probability_deviation", 0.0))
        probability_deviation = float(payload.get("probability_deviation", probability_deviation))
        if probability_deviation < 0.0:
            raise ValueError("ambiguity probability_deviation must be non-negative")

        expected_shortfall_alpha = float(payload.get("expected_shortfall_alpha", 0.2))
        if not 0.0 < expected_shortfall_alpha <= 1.0:
            raise ValueError("expected_shortfall_alpha must be in (0, 1]")

        robust_metric = str(
            payload.get("robust_metric", "worst_case_expected_shortfall"),
        ).strip()
        supported_metrics = {
            "worst_case_expected_utility",
            "worst_case_expected_shortfall",
        }
        if robust_metric not in supported_metrics:
            supported_text = ", ".join(sorted(supported_metrics))
            raise ValueError(
                f"Unsupported robust_metric '{robust_metric}'. Supported values: {supported_text}",
            )

        raw_risk_metric = payload.get("risk_metric")
        risk_metric = str(raw_risk_metric).strip() if raw_risk_metric is not None else None
        supported_risk_metrics = {"worst_case_mean", "expected_shortfall"}
        if risk_metric is not None and risk_metric not in supported_risk_metrics:
            supported_text = ", ".join(sorted(supported_risk_metrics))
            raise ValueError(
                f"Unsupported ambiguity_aware_decision.risk_metric '{risk_metric}'. "
                f"Supported values: {supported_text}",
            )
        if risk_metric is not None:
            warnings.warn(
                "ambiguity_aware_decision.risk_metric is deprecated; "
                "use fleet decision_attitude values risk_neutral, risk_averse_mean, "
                "or risk_averse_expected_shortfall to select the NPV-based mode.",
                DeprecationWarning,
                stacklevel=2,
            )

        probability_table = _optional_text(payload.get("probability_table"))
        if not scenario_ids:
            scenario_ids = ("baseline",)
            probabilities = {"baseline": 1.0}

        raw_belief_sets = payload.get("belief_sets") or ()
        belief_sets = tuple(str(item).strip() for item in raw_belief_sets if str(item).strip())
        probability_input_format = str(payload.get("probability_input_format", "auto")).strip()
        tail_alpha = float(payload.get("tail_alpha", 0.95))
        if not 0.0 < tail_alpha < 1.0:
            raise ValueError("ambiguity_aware_decision.tail_alpha must be in (0, 1)")
        probability_tolerance = float(payload.get("probability_tolerance", 1e-8))
        if probability_tolerance <= 0.0:
            raise ValueError("ambiguity_aware_decision.probability_tolerance must be positive")

        return cls(
            enabled=True,
            scenario_ids=scenario_ids,
            probabilities=probabilities,
            ambiguity_enabled=bool(ambiguity_payload.get("enabled", False)),
            probability_deviation=probability_deviation,
            expected_shortfall_alpha=expected_shortfall_alpha,
            robust_metric=robust_metric,
            risk_metric=risk_metric,
            probability_table=probability_table,
            belief_sets=belief_sets,
            probability_input_format=probability_input_format,
            tail_alpha=tail_alpha,
            probability_tolerance=probability_tolerance,
            write_debug_outputs=bool(payload.get("write_debug_outputs", True)),
            risk_neutral_belief_set=_optional_text(payload.get("risk_neutral_belief_set")),
        )

    def probability_table_path(self, base_path: Path) -> Path | None:
        if self.probability_table is None:
            return None
        table_path = Path(self.probability_table)
        if not table_path.is_absolute():
            table_path = base_path / table_path
        return table_path.resolve()


SUPPORTED_RESIDUAL_VALUE_METHODS = ("none", "straight_line_remaining_life")

# Mirrors AURIS's CASHFLOW_MODE_ALIASES: several spellings collapse onto the
# same two underlying modes.
CASHFLOW_MODE_ALIASES = {
    "": "component_based",
    "component": "component_based",
    "component_based": "component_based",
    "direct": "direct_net_operating_cost",
    "direct_net_cost": "direct_net_operating_cost",
    "direct_net_operating_cost": "direct_net_operating_cost",
}
SUPPORTED_CASHFLOW_MODES = ("component_based", "direct_net_operating_cost")


@dataclass(frozen=True)
class InvestmentTimingConfig:
    include_continue_option: bool = False
    residual_value_method: str = "none"
    minimum_holding_period: int = 0
    include_life_extension: bool = False
    include_shutdown: bool = False
    cashflow_mode: str = "component_based"
    direct_net_operating_cost_parameter: str = ""
    direct_revenue_parameter: str = ""

    def __post_init__(self) -> None:
        if self.residual_value_method not in SUPPORTED_RESIDUAL_VALUE_METHODS:
            supported = ", ".join(SUPPORTED_RESIDUAL_VALUE_METHODS)
            raise ValueError(
                f"Unsupported investment_timing.residual_value_method "
                f"'{self.residual_value_method}'. Supported values: {supported}",
            )
        if self.minimum_holding_period < 0:
            raise ValueError("investment_timing.minimum_holding_period must be >= 0")
        # AURIS itself does not implement these two knobs either (its own
        # validate_config raises NotImplementedError immediately when either
        # is set) - this ports the reserved, fail-fast surface, not a working
        # feature that doesn't exist upstream.
        if self.include_life_extension:
            raise NotImplementedError(
                "investment_timing.include_life_extension is not implemented yet",
            )
        if self.include_shutdown:
            raise NotImplementedError(
                "investment_timing.include_shutdown is not implemented yet",
            )
        if self.cashflow_mode not in SUPPORTED_CASHFLOW_MODES:
            supported = ", ".join(SUPPORTED_CASHFLOW_MODES)
            raise ValueError(
                f"Unsupported investment_timing.cashflow_mode "
                f"'{self.cashflow_mode}'. Supported values: {supported}",
            )
        if (
            self.cashflow_mode == "direct_net_operating_cost"
            and not self.direct_net_operating_cost_parameter
        ):
            raise ValueError(
                "investment_timing.direct_net_operating_cost_parameter is required "
                "when cashflow_mode is 'direct_net_operating_cost'",
            )

    @classmethod
    def from_dict(cls, payload: dict | None) -> InvestmentTimingConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("investment_timing must be a mapping")
        raw_cashflow_mode = str(payload.get("cashflow_mode", "")).strip().lower()
        cashflow_mode = CASHFLOW_MODE_ALIASES.get(
            raw_cashflow_mode,
            raw_cashflow_mode or "component_based",
        )
        return cls(
            include_continue_option=bool(payload.get("include_continue_option", False)),
            residual_value_method=str(payload.get("residual_value_method", "none")).strip()
            or "none",
            minimum_holding_period=int(payload.get("minimum_holding_period", 0)),
            include_life_extension=bool(payload.get("include_life_extension", False)),
            include_shutdown=bool(payload.get("include_shutdown", False)),
            cashflow_mode=cashflow_mode,
            direct_net_operating_cost_parameter=str(
                payload.get("direct_net_operating_cost_parameter", ""),
            ).strip(),
            direct_revenue_parameter=str(payload.get("direct_revenue_parameter", "")).strip(),
        )


@dataclass
class NATMScenario:
    name: str
    start_year: int
    end_year: int
    sectors: dict[str, tuple[str, ...]]
    preprocessing: dict[str, AviationPreprocessingConfig] = field(default_factory=dict)
    ambiguity_aware_decision: AmbiguityAwareDecisionConfig = field(
        default_factory=AmbiguityAwareDecisionConfig,
    )
    investment_timing: InvestmentTimingConfig = field(default_factory=InvestmentTimingConfig)
    base_path: Path = field(default_factory=lambda: Path("."), repr=False)

    def __post_init__(self) -> None:
        if self.end_year < self.start_year:
            raise ValueError("end_year must be greater than or equal to start_year")
        if not self.sectors:
            raise ValueError("sectors must include at least one sector")

        unsupported = set(self.sectors) - {"aviation", "maritime"}
        if unsupported:
            unsupported_text = ", ".join(sorted(unsupported))
            raise ValueError(f"Unsupported sectors in sectors: {unsupported_text}")

    @property
    def enabled_sectors(self) -> tuple[str, ...]:
        return tuple(self.sectors.keys())

    @property
    def steps(self) -> int:
        return self.end_year - self.start_year + 1

    def is_sector_enabled(self, sector_name: str) -> bool:
        return sector_name in self.sectors

    def applications_for_sector(self, sector_name: str) -> tuple[str, ...]:
        return self.sectors.get(sector_name, ())

    def is_application_enabled(self, sector_name: str, application_name: str) -> bool:
        return application_name in self.applications_for_sector(sector_name)

    def operator_input_path(self, sector_name: str) -> Path | None:
        default_path = self.base_path / f"{sector_name}_operators.csv"
        if default_path.exists():
            return default_path.resolve()
        return None

    def environment_input_path(self, name: str) -> Path | None:
        default_path = self.base_path / f"{name}.csv"
        if default_path.exists():
            return default_path.resolve()
        return None

    def aviation_preprocessing_config(self) -> AviationPreprocessingConfig | None:
        return self.preprocessing.get("aviation")

    @classmethod
    def from_dict(cls, payload: dict) -> NATMScenario:
        raw_sectors = payload.get("sectors")
        if not isinstance(raw_sectors, dict) or not raw_sectors:
            raise ValueError("scenario.yaml must define sectors as a mapping")

        normalized_sectors: dict[str, tuple[str, ...]] = {}
        for sector_name, applications in raw_sectors.items():
            if applications is None:
                normalized_sectors[str(sector_name)] = ()
                continue
            if not isinstance(applications, list):
                raise ValueError(f"Sector '{sector_name}' must map to a list of applications")
            normalized_sectors[str(sector_name)] = tuple(str(item).strip() for item in applications)

        preprocessing = _parse_preprocessing(payload.get("preprocessing"))
        ambiguity_aware_decision = AmbiguityAwareDecisionConfig.from_dict(
            payload.get("ambiguity_aware_decision"),
        )
        investment_timing = InvestmentTimingConfig.from_dict(payload.get("investment_timing"))

        return cls(
            name=payload["name"],
            start_year=payload["start_year"],
            end_year=payload["end_year"],
            sectors=normalized_sectors,
            preprocessing=preprocessing,
            ambiguity_aware_decision=ambiguity_aware_decision,
            investment_timing=investment_timing,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> NATMScenario:
        scenario_path = Path(path)
        payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        scenario = cls.from_dict(payload)
        scenario.base_path = scenario_path.parent.resolve()
        probability_table_path = scenario.ambiguity_aware_decision.probability_table_path(
            scenario.base_path,
        )
        if probability_table_path is not None and not probability_table_path.exists():
            raise ValueError(f"Ambiguity probability table not found: {probability_table_path}")
        return scenario


def _parse_preprocessing(payload: object) -> dict[str, AviationPreprocessingConfig]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("preprocessing must be a mapping")

    unsupported = set(payload) - {"aviation"}
    if unsupported:
        unsupported_text = ", ".join(sorted(str(item) for item in unsupported))
        raise ValueError(f"Unsupported preprocessing sections: {unsupported_text}")

    aviation_payload = payload.get("aviation")
    if aviation_payload is None:
        return {}
    return {"aviation": AviationPreprocessingConfig.from_dict(aviation_payload)}
