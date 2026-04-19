from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from natm.core.agents import SectorAgent
from natm.core.scenario import NATMScenario


@dataclass
class YearSnapshot:
    year: int
    aviation_total_assets: float
    aviation_alternative_share: float
    maritime_total_assets: float
    maritime_alternative_share: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


class NATMModel:
    def __init__(self, scenario: NATMScenario) -> None:
        self.scenario = scenario
        self.current_year = scenario.start_year
        self.aviation = SectorAgent("aviation", scenario.aviation)
        self.maritime = SectorAgent("maritime", scenario.maritime)
        self.history = [self._snapshot()]

    def _snapshot(self) -> YearSnapshot:
        return YearSnapshot(
            year=self.current_year,
            aviation_total_assets=self.aviation.state.total_assets,
            aviation_alternative_share=self.aviation.state.alternative_share,
            maritime_total_assets=self.maritime.state.total_assets,
            maritime_alternative_share=self.maritime.state.alternative_share,
        )

    def step(self) -> YearSnapshot:
        if self.current_year >= self.scenario.end_year:
            return self.history[-1]

        self.current_year += 1
        self.aviation.step()
        self.maritime.step()
        snapshot = self._snapshot()
        self.history.append(snapshot)
        return snapshot

    def run(self) -> list[YearSnapshot]:
        while self.current_year < self.scenario.end_year:
            self.step()
        return self.history

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(snapshot.to_dict() for snapshot in self.history)
