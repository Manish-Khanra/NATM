from __future__ import annotations

from dataclasses import dataclass, field


def _ensure_nonnegative(name: str, value: float) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be nonnegative")


def _ensure_fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass
class RampValue:
    start: float
    end: float

    def __post_init__(self) -> None:
        self.start = float(self.start)
        self.end = float(self.end)

    @classmethod
    def from_dict(cls, payload: dict) -> RampValue:
        return cls(start=payload["start"], end=payload["end"])

    def value_at(self, position: int, total_positions: int) -> float:
        if total_positions <= 0:
            return self.end
        progress = position / total_positions
        return self.start + (self.end - self.start) * progress


@dataclass
class SectorPolicySettings:
    clean_fuel_subsidy: RampValue = field(default_factory=lambda: RampValue(start=0.0, end=0.0))
    adoption_mandate: RampValue = field(default_factory=lambda: RampValue(start=0.0, end=0.0))

    def __post_init__(self) -> None:
        for value in (
            self.clean_fuel_subsidy.start,
            self.clean_fuel_subsidy.end,
            self.adoption_mandate.start,
            self.adoption_mandate.end,
        ):
            _ensure_fraction("sector policy value", value)

    @classmethod
    def from_dict(cls, payload: dict) -> SectorPolicySettings:
        return cls(
            clean_fuel_subsidy=RampValue.from_dict(payload["clean_fuel_subsidy"]),
            adoption_mandate=RampValue.from_dict(payload["adoption_mandate"]),
        )

    def for_year(self, position: int, total_positions: int) -> SectorPolicySignal:
        return SectorPolicySignal(
            clean_fuel_subsidy=self.clean_fuel_subsidy.value_at(position, total_positions),
            adoption_mandate=self.adoption_mandate.value_at(position, total_positions),
        )


@dataclass
class PolicySettings:
    carbon_price: RampValue = field(default_factory=lambda: RampValue(start=0.0, end=0.0))
    aviation: SectorPolicySettings = field(default_factory=SectorPolicySettings)
    maritime: SectorPolicySettings = field(default_factory=SectorPolicySettings)

    def __post_init__(self) -> None:
        _ensure_nonnegative("carbon_price.start", self.carbon_price.start)
        _ensure_nonnegative("carbon_price.end", self.carbon_price.end)

    @classmethod
    def from_dict(cls, payload: dict) -> PolicySettings:
        return cls(
            carbon_price=RampValue.from_dict(payload["carbon_price"]),
            aviation=SectorPolicySettings.from_dict(payload["aviation"]),
            maritime=SectorPolicySettings.from_dict(payload["maritime"]),
        )

    def for_year(self, position: int, total_positions: int) -> PolicySignal:
        return PolicySignal(
            carbon_price=self.carbon_price.value_at(position, total_positions),
            aviation=self.aviation.for_year(position, total_positions),
            maritime=self.maritime.for_year(position, total_positions),
        )


@dataclass(frozen=True)
class SectorPolicySignal:
    clean_fuel_subsidy: float
    adoption_mandate: float


@dataclass(frozen=True)
class PolicySignal:
    carbon_price: float
    aviation: SectorPolicySignal
    maritime: SectorPolicySignal
