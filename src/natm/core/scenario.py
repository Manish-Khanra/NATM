from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SectorParameters(BaseModel):
    initial_fleet: int = Field(ge=0)
    annual_growth_rate: float = 0.0
    retirement_rate: float = Field(ge=0.0, le=1.0)
    alternative_share: float = Field(default=0.0, ge=0.0, le=1.0)
    adoption_sensitivity: float = Field(default=0.10, ge=0.0, le=1.0)


class NATMScenario(BaseModel):
    name: str
    start_year: int
    end_year: int
    aviation: SectorParameters
    maritime: SectorParameters

    @property
    def steps(self) -> int:
        return self.end_year - self.start_year + 1

    @classmethod
    def from_yaml(cls, path: str | Path) -> NATMScenario:
        scenario_path = Path(path)
        payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        return cls.model_validate(payload)
