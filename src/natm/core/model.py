from __future__ import annotations

from dataclasses import asdict, dataclass

import mesa
import pandas as pd

from natm.core.agents import (
    AviationOperatorAgent,
    MaritimeOperatorAgent,
    OperatorProfile,
    SectorMarketContext,
)
from natm.core.scenario import NATMScenario, SectorParameters


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


@dataclass
class YearSnapshot:
    year: int
    carbon_price: float
    aviation_total_assets: float
    aviation_alternative_share: float
    aviation_transition_pressure: float
    aviation_infrastructure_readiness: float
    aviation_effective_conventional_cost: float
    aviation_effective_alternative_cost: float
    aviation_policy_support: float
    aviation_mandate_share: float
    maritime_total_assets: float
    maritime_alternative_share: float
    maritime_transition_pressure: float
    maritime_infrastructure_readiness: float
    maritime_effective_conventional_cost: float
    maritime_effective_alternative_cost: float
    maritime_policy_support: float
    maritime_mandate_share: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


class NATMModel(mesa.Model):
    """Mesa-native NATM model with multiple operator agents per sector."""

    sector_agent_classes = {
        "aviation": AviationOperatorAgent,
        "maritime": MaritimeOperatorAgent,
    }

    def __init__(self, scenario: NATMScenario, *, seed: int | None = None) -> None:
        super().__init__(seed=seed)
        self.scenario = scenario

        aviation_profiles = self._build_operator_profiles("aviation", scenario.aviation)
        maritime_profiles = self._build_operator_profiles("maritime", scenario.maritime)

        AviationOperatorAgent.create_agents(self, len(aviation_profiles), profile=aviation_profiles)
        MaritimeOperatorAgent.create_agents(self, len(maritime_profiles), profile=maritime_profiles)

        self.current_sector_context = self._build_sector_context()
        self.datacollector = mesa.DataCollector(
            model_reporters={
                "year": "current_year",
                "carbon_price": lambda m: m.current_policy_signal.carbon_price,
                "aviation_total_assets": lambda m: m.sector_total_assets("aviation"),
                "aviation_alternative_share": lambda m: m.sector_alternative_share("aviation"),
                "aviation_transition_pressure": lambda m: m.sector_mean(
                    "aviation",
                    "transition_pressure",
                ),
                "aviation_infrastructure_readiness": lambda m: m.sector_mean(
                    "aviation",
                    "infrastructure_readiness",
                ),
                "aviation_effective_conventional_cost": lambda m: m.sector_mean(
                    "aviation",
                    "effective_conventional_cost",
                ),
                "aviation_effective_alternative_cost": lambda m: m.sector_mean(
                    "aviation",
                    "effective_alternative_cost",
                ),
                "aviation_policy_support": lambda m: m.sector_mean("aviation", "policy_support"),
                "aviation_mandate_share": lambda m: m.sector_mean("aviation", "mandate_share"),
                "maritime_total_assets": lambda m: m.sector_total_assets("maritime"),
                "maritime_alternative_share": lambda m: m.sector_alternative_share("maritime"),
                "maritime_transition_pressure": lambda m: m.sector_mean(
                    "maritime",
                    "transition_pressure",
                ),
                "maritime_infrastructure_readiness": lambda m: m.sector_mean(
                    "maritime",
                    "infrastructure_readiness",
                ),
                "maritime_effective_conventional_cost": lambda m: m.sector_mean(
                    "maritime",
                    "effective_conventional_cost",
                ),
                "maritime_effective_alternative_cost": lambda m: m.sector_mean(
                    "maritime",
                    "effective_alternative_cost",
                ),
                "maritime_policy_support": lambda m: m.sector_mean("maritime", "policy_support"),
                "maritime_mandate_share": lambda m: m.sector_mean("maritime", "mandate_share"),
            },
            agent_reporters={
                "operator_name": "operator_name",
                "sector_name": "sector_name",
                "year": "current_year",
                "conventional_assets": "conventional_assets",
                "alternative_assets": "alternative_assets",
                "total_assets": "total_assets",
                "alternative_share": "alternative_share",
                "transition_pressure": "transition_pressure",
                "infrastructure_readiness": "infrastructure_readiness",
                "effective_conventional_cost": "effective_conventional_cost",
                "effective_alternative_cost": "effective_alternative_cost",
                "policy_support": "policy_support",
                "mandate_share": "mandate_share",
                "peer_influence": "peer_influence",
            },
        )

        self.history = [self._snapshot()]
        self.datacollector.collect(self)

    @property
    def current_year(self) -> int:
        return self.scenario.start_year + self.steps

    @property
    def current_policy_signal(self):
        return self.scenario.policy_signal(self.current_year)

    def get_sector_agents(self, sector_name: str):
        return self.agents_by_type[self.sector_agent_classes[sector_name]]

    def sector_total_assets(self, sector_name: str) -> float:
        return sum(agent.total_assets for agent in self.get_sector_agents(sector_name))

    def sector_alternative_assets(self, sector_name: str) -> float:
        return sum(agent.alternative_assets for agent in self.get_sector_agents(sector_name))

    def sector_alternative_share(self, sector_name: str) -> float:
        total_assets = self.sector_total_assets(sector_name)
        if total_assets == 0:
            return 0.0
        return self.sector_alternative_assets(sector_name) / total_assets

    def sector_mean(self, sector_name: str, attribute: str) -> float:
        agents = list(self.get_sector_agents(sector_name))
        return _mean([getattr(agent, attribute) for agent in agents])

    def _bounded_multiplier(
        self,
        base: float,
        variation: float,
        minimum: float,
        maximum: float,
    ) -> float:
        scaled = base * (1.0 + self.rng.uniform(-variation, variation))
        return min(maximum, max(minimum, scaled))

    def _build_operator_profiles(
        self,
        sector_name: str,
        params: SectorParameters,
    ) -> list[OperatorProfile]:
        raw_sizes = self.rng.lognormal(
            mean=0.0,
            sigma=max(params.fleet_variation, 1e-6),
            size=params.operator_count,
        )
        size_shares = raw_sizes / raw_sizes.sum()

        profiles: list[OperatorProfile] = []
        for index, share in enumerate(size_shares, start=1):
            initial_total_assets = float(params.initial_fleet) * float(share)
            initial_alternative_share = self._bounded_multiplier(
                params.alternative_share,
                params.sensitivity_variation,
                0.0,
                0.95,
            )
            adoption_sensitivity = self._bounded_multiplier(
                params.adoption_sensitivity,
                params.sensitivity_variation,
                0.0,
                1.0,
            )
            conventional_energy_cost = self._bounded_multiplier(
                params.conventional_energy_cost,
                params.cost_variation,
                0.01,
                10.0,
            )
            alternative_energy_cost = self._bounded_multiplier(
                params.alternative_energy_cost,
                params.cost_variation,
                0.01,
                10.0,
            )
            infrastructure_readiness = self._bounded_multiplier(
                params.infrastructure_readiness,
                params.readiness_variation,
                0.0,
                1.0,
            )
            peer_influence = self._bounded_multiplier(
                params.peer_influence,
                params.sensitivity_variation,
                0.0,
                1.0,
            )

            profiles.append(
                OperatorProfile(
                    operator_name=f"{sector_name[:3]}_{index:02d}",
                    conventional_assets=initial_total_assets * (1.0 - initial_alternative_share),
                    alternative_assets=initial_total_assets * initial_alternative_share,
                    annual_growth_rate=params.annual_growth_rate,
                    retirement_rate=params.retirement_rate,
                    adoption_sensitivity=adoption_sensitivity,
                    conventional_energy_cost=conventional_energy_cost,
                    alternative_energy_cost=alternative_energy_cost,
                    emissions_intensity=params.emissions_intensity,
                    infrastructure_readiness=infrastructure_readiness,
                    infrastructure_build_rate=params.infrastructure_build_rate,
                    learning_rate=params.learning_rate,
                    peer_influence=peer_influence,
                )
            )
        return profiles

    def _build_sector_context(self) -> dict[str, SectorMarketContext]:
        contexts: dict[str, SectorMarketContext] = {}
        for sector_name in self.sector_agent_classes:
            contexts[sector_name] = SectorMarketContext(
                average_alternative_share=self.sector_alternative_share(sector_name),
                average_infrastructure_readiness=self.sector_mean(
                    sector_name,
                    "infrastructure_readiness",
                ),
                average_transition_pressure=self.sector_mean(
                    sector_name,
                    "transition_pressure",
                ),
            )
        return contexts

    def _snapshot(self) -> YearSnapshot:
        policy_signal = self.current_policy_signal
        return YearSnapshot(
            year=self.current_year,
            carbon_price=policy_signal.carbon_price,
            aviation_total_assets=self.sector_total_assets("aviation"),
            aviation_alternative_share=self.sector_alternative_share("aviation"),
            aviation_transition_pressure=self.sector_mean("aviation", "transition_pressure"),
            aviation_infrastructure_readiness=self.sector_mean(
                "aviation",
                "infrastructure_readiness",
            ),
            aviation_effective_conventional_cost=self.sector_mean(
                "aviation",
                "effective_conventional_cost",
            ),
            aviation_effective_alternative_cost=self.sector_mean(
                "aviation",
                "effective_alternative_cost",
            ),
            aviation_policy_support=self.sector_mean("aviation", "policy_support"),
            aviation_mandate_share=self.sector_mean("aviation", "mandate_share"),
            maritime_total_assets=self.sector_total_assets("maritime"),
            maritime_alternative_share=self.sector_alternative_share("maritime"),
            maritime_transition_pressure=self.sector_mean("maritime", "transition_pressure"),
            maritime_infrastructure_readiness=self.sector_mean(
                "maritime",
                "infrastructure_readiness",
            ),
            maritime_effective_conventional_cost=self.sector_mean(
                "maritime",
                "effective_conventional_cost",
            ),
            maritime_effective_alternative_cost=self.sector_mean(
                "maritime",
                "effective_alternative_cost",
            ),
            maritime_policy_support=self.sector_mean("maritime", "policy_support"),
            maritime_mandate_share=self.sector_mean("maritime", "mandate_share"),
        )

    def step(self) -> None:
        if self.current_year > self.scenario.end_year:
            self.running = False
            return

        self.current_sector_context = self._build_sector_context()
        self.agents_by_type[AviationOperatorAgent].shuffle_do("step")
        self.agents_by_type[MaritimeOperatorAgent].shuffle_do("step")

        self.history.append(self._snapshot())
        self.datacollector.collect(self)

        if self.current_year >= self.scenario.end_year:
            self.running = False

    def run(self) -> list[YearSnapshot]:
        self.run_model()
        return self.history

    def to_frame(self) -> pd.DataFrame:
        return self.datacollector.get_model_vars_dataframe().reset_index(drop=True)

    def to_agent_frame(self) -> pd.DataFrame:
        agent_frame = self.datacollector.get_agent_vars_dataframe().reset_index()
        return agent_frame.rename(columns={"Step": "step", "AgentID": "agent_id"})
