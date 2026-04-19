from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from natm.core.policy import PolicySettings, PolicySignal


def _ensure_fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _ensure_nonnegative(name: str, value: float) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass
class SectorParameters:
    initial_fleet: int
    annual_growth_rate: float = 0.0
    retirement_rate: float = 0.0
    alternative_share: float = 0.0
    adoption_sensitivity: float = 0.10
    conventional_energy_cost: float = 0.0
    alternative_energy_cost: float = 0.0
    emissions_intensity: float = 0.0
    infrastructure_readiness: float = 0.0
    infrastructure_build_rate: float = 0.02
    learning_rate: float = 0.10
    operator_count: int = 8
    fleet_variation: float = 0.35
    sensitivity_variation: float = 0.20
    cost_variation: float = 0.10
    readiness_variation: float = 0.15
    peer_influence: float = 0.20

    def __post_init__(self) -> None:
        if self.initial_fleet < 0:
            raise ValueError("initial_fleet must be nonnegative")
        if self.operator_count < 1:
            raise ValueError("operator_count must be at least 1")

        for name, value in (
            ("annual_growth_rate", self.annual_growth_rate),
            ("conventional_energy_cost", self.conventional_energy_cost),
            ("alternative_energy_cost", self.alternative_energy_cost),
            ("emissions_intensity", self.emissions_intensity),
            ("fleet_variation", self.fleet_variation),
            ("sensitivity_variation", self.sensitivity_variation),
            ("cost_variation", self.cost_variation),
            ("readiness_variation", self.readiness_variation),
        ):
            _ensure_nonnegative(name, float(value))

        for name, value in (
            ("retirement_rate", self.retirement_rate),
            ("alternative_share", self.alternative_share),
            ("adoption_sensitivity", self.adoption_sensitivity),
            ("infrastructure_readiness", self.infrastructure_readiness),
            ("infrastructure_build_rate", self.infrastructure_build_rate),
            ("learning_rate", self.learning_rate),
            ("peer_influence", self.peer_influence),
        ):
            _ensure_fraction(name, float(value))

    @classmethod
    def from_dict(cls, payload: dict) -> SectorParameters:
        return cls(**payload)


@dataclass
class NATMScenario:
    name: str
    start_year: int
    end_year: int
    policy: PolicySettings
    aviation: SectorParameters
    maritime: SectorParameters

    def __post_init__(self) -> None:
        if self.end_year < self.start_year:
            raise ValueError("end_year must be greater than or equal to start_year")

    @property
    def steps(self) -> int:
        return self.end_year - self.start_year + 1

    @property
    def transition_years(self) -> int:
        return max(self.end_year - self.start_year, 1)

    def policy_signal(self, year: int) -> PolicySignal:
        clamped_year = min(max(year, self.start_year), self.end_year)
        position = clamped_year - self.start_year
        return self.policy.for_year(position=position, total_positions=self.transition_years)

    @classmethod
    def from_dict(cls, payload: dict) -> NATMScenario:
        return cls(
            name=payload["name"],
            start_year=payload["start_year"],
            end_year=payload["end_year"],
            policy=PolicySettings.from_dict(payload["policy"]),
            aviation=SectorParameters.from_dict(payload["aviation"]),
            maritime=SectorParameters.from_dict(payload["maritime"]),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> NATMScenario:
        scenario_path = Path(path)
        payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        return cls.from_dict(payload)
