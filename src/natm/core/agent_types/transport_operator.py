from __future__ import annotations

from dataclasses import dataclass

import mesa

from natm.core.agent_types.base import BaseOperatorAgent
from natm.core.policy import SectorPolicySignal


@dataclass(frozen=True)
class OperatorProfile:
    operator_name: str
    operator_country: str
    conventional_assets: float
    alternative_assets: float
    annual_growth_rate: float
    retirement_rate: float
    adoption_sensitivity: float
    conventional_energy_cost: float
    alternative_energy_cost: float
    emissions_intensity: float
    infrastructure_readiness: float
    infrastructure_build_rate: float
    learning_rate: float
    peer_influence: float


@dataclass(frozen=True)
class SectorMarketContext:
    average_alternative_share: float
    average_infrastructure_readiness: float
    average_transition_pressure: float


class TransportOperatorAgent(BaseOperatorAgent):
    sector_name = "transport"

    def __init__(self, model: mesa.Model, profile: OperatorProfile) -> None:
        super().__init__(
            model,
            operator_name=profile.operator_name,
            operator_country=profile.operator_country,
        )
        self.conventional_assets = profile.conventional_assets
        self.alternative_assets = profile.alternative_assets
        self.annual_growth_rate = profile.annual_growth_rate
        self.retirement_rate = profile.retirement_rate
        self.adoption_sensitivity = profile.adoption_sensitivity
        self.conventional_energy_cost = profile.conventional_energy_cost
        self.alternative_energy_cost = profile.alternative_energy_cost
        self.emissions_intensity = profile.emissions_intensity
        self.infrastructure_readiness = profile.infrastructure_readiness
        self.infrastructure_build_rate = profile.infrastructure_build_rate
        self.learning_rate = profile.learning_rate
        self.peer_influence = profile.peer_influence

        self.transition_pressure = self.alternative_share
        self.effective_conventional_cost = self.conventional_energy_cost
        self.effective_alternative_cost = self.alternative_energy_cost

    @property
    def current_policy_signal(self) -> SectorPolicySignal:
        return getattr(self.model.current_policy_signal, self.sector_name)

    @property
    def market_context(self) -> SectorMarketContext:
        return self.model.current_sector_context[self.sector_name]

    def step(self) -> None:
        policy_signal = self.current_policy_signal
        carbon_price = self.model.current_policy_signal.carbon_price
        market_context = self.market_context
        environment_signal = self.environment_signal

        total_assets = self.total_assets
        target_assets = total_assets * (1 + self.annual_growth_rate)

        self.effective_conventional_cost = (
            self.conventional_energy_cost + carbon_price * self.emissions_intensity
        )
        learning_multiplier = max(
            0.50,
            1.0 - self.learning_rate * self.alternative_share,
        )
        self.effective_alternative_cost = (
            self.alternative_energy_cost
            * learning_multiplier
            * (1.0 - policy_signal.clean_fuel_subsidy)
            * (1.0 - 0.20 * environment_signal.clean_fuel_availability)
        )

        denominator = max(
            self.effective_conventional_cost,
            self.effective_alternative_cost,
            1.0,
        )
        cost_advantage = max(
            -1.0,
            min(
                1.0,
                (self.effective_conventional_cost - self.effective_alternative_cost) / denominator,
            ),
        )

        peer_signal = (
            0.65 * market_context.average_alternative_share
            + 0.35 * market_context.average_transition_pressure
        )
        blended_infrastructure = (
            0.40 * self.infrastructure_readiness
            + 0.35 * market_context.average_infrastructure_readiness
            + 0.25 * environment_signal.infrastructure_readiness
        )

        self.infrastructure_readiness = min(
            1.0,
            blended_infrastructure
            + self.infrastructure_build_rate * (0.5 + policy_signal.clean_fuel_subsidy)
            + 0.04 * peer_signal,
        )
        mandate_gap = max(policy_signal.adoption_mandate - self.alternative_share, 0.0)
        effective_retirement_rate = min(
            1.0,
            self.retirement_rate + 0.20 * mandate_gap,
        )

        conventional_retirements = self.conventional_assets * effective_retirement_rate
        alternative_retirements = self.alternative_assets * effective_retirement_rate

        surviving_conventional = self.conventional_assets - conventional_retirements
        surviving_alternative = self.alternative_assets - alternative_retirements
        surviving_total = surviving_conventional + surviving_alternative
        replacements_needed = max(target_assets - surviving_total, 0.0)

        self.policy_support = min(
            1.0,
            0.55 * policy_signal.clean_fuel_subsidy + 0.45 * policy_signal.adoption_mandate,
        )
        peer_pressure = self.peer_influence * peer_signal
        world_pressure = (
            0.35 * environment_signal.clean_fuel_availability
            + 0.35 * environment_signal.policy_alignment
            + 0.30 * environment_signal.corridor_exposure
        )
        blended_support = min(
            1.0,
            0.75 * self.policy_support + 0.25 * world_pressure,
        )
        projected_share = min(
            0.99,
            max(
                policy_signal.adoption_mandate,
                0.02
                + self.alternative_share
                + self.adoption_sensitivity * (1.0 - self.alternative_share)
                + 0.24 * cost_advantage
                + 0.18 * self.infrastructure_readiness
                + 0.16 * blended_support
                + 0.12 * peer_pressure,
            ),
        )
        self.transition_pressure = min(
            0.99,
            max(
                0.01,
                0.20 * self.alternative_share
                + 0.25 * max(cost_advantage, -0.25)
                + 0.18 * self.infrastructure_readiness
                + 0.17 * blended_support
                + 0.20 * peer_pressure,
            ),
        )

        alternative_additions = replacements_needed * projected_share
        conventional_additions = replacements_needed - alternative_additions

        self.conventional_assets = surviving_conventional + conventional_additions
        self.alternative_assets = surviving_alternative + alternative_additions
        self.mandate_share = policy_signal.adoption_mandate
        self.policy_support = blended_support


class AviationOperatorAgent(TransportOperatorAgent):
    sector_name = "aviation"


class MaritimeOperatorAgent(TransportOperatorAgent):
    sector_name = "maritime"
