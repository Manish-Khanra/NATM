from __future__ import annotations

from dataclasses import dataclass

from natm.core.scenario import SectorParameters


@dataclass
class SectorState:
    conventional_assets: float
    alternative_assets: float

    @property
    def total_assets(self) -> float:
        return self.conventional_assets + self.alternative_assets

    @property
    def alternative_share(self) -> float:
        total = self.total_assets
        if total == 0:
            return 0.0
        return self.alternative_assets / total


class SectorAgent:
    def __init__(self, name: str, params: SectorParameters) -> None:
        self.name = name
        self.params = params

        initial_alternative = params.initial_fleet * params.alternative_share
        self.state = SectorState(
            conventional_assets=params.initial_fleet - initial_alternative,
            alternative_assets=initial_alternative,
        )

    def step(self) -> SectorState:
        state = self.state
        total_assets = state.total_assets
        target_assets = total_assets * (1 + self.params.annual_growth_rate)

        conventional_retirements = state.conventional_assets * self.params.retirement_rate
        alternative_retirements = state.alternative_assets * self.params.retirement_rate

        surviving_conventional = state.conventional_assets - conventional_retirements
        surviving_alternative = state.alternative_assets - alternative_retirements
        surviving_total = surviving_conventional + surviving_alternative

        replacements_needed = max(target_assets - surviving_total, 0.0)
        projected_share = min(
            0.99,
            state.alternative_share
            + self.params.adoption_sensitivity * (1.0 - state.alternative_share),
        )

        alternative_additions = replacements_needed * projected_share
        conventional_additions = replacements_needed - alternative_additions

        self.state = SectorState(
            conventional_assets=surviving_conventional + conventional_additions,
            alternative_assets=surviving_alternative + alternative_additions,
        )
        return self.state
