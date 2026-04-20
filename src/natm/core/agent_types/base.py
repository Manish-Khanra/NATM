from __future__ import annotations

from typing import Any

import mesa

from natm.core.environment import CountryEnvironmentSignal


class BaseOperatorAgent(mesa.Agent):
    sector_name = "transport"

    def __init__(
        self,
        model: mesa.Model,
        *,
        operator_name: str,
        operator_country: str,
    ) -> None:
        super().__init__(model)
        self.operator_name = operator_name
        self.operator_country = operator_country
        self.transition_pressure = 0.0
        self.infrastructure_readiness = 0.0
        self.effective_conventional_cost = 0.0
        self.effective_alternative_cost = 0.0
        self.policy_support = 0.0
        self.mandate_share = 0.0
        self.conventional_assets = 0.0
        self.alternative_assets = 0.0
        self.peer_influence = 0.0

    @property
    def current_year(self) -> int:
        return self.model.current_year

    @property
    def total_assets(self) -> float:
        return self.conventional_assets + self.alternative_assets

    @property
    def alternative_share(self) -> float:
        if self.total_assets == 0:
            return 0.0
        return self.alternative_assets / self.total_assets

    @property
    def environment_signal(self) -> CountryEnvironmentSignal:
        return self.model.environment.signal_for(self.operator_country, self.sector_name)

    def get_output_metadata(self) -> dict[str, Any]:
        return {
            "operator_name": self.operator_name,
            "operator_country": self.operator_country,
            "sector_name": self.sector_name,
            "year": self.current_year,
            "conventional_assets": self.conventional_assets,
            "alternative_assets": self.alternative_assets,
            "total_assets": self.total_assets,
            "alternative_share": self.alternative_share,
            "transition_pressure": self.transition_pressure,
            "infrastructure_readiness": self.infrastructure_readiness,
            "effective_conventional_cost": self.effective_conventional_cost,
            "effective_alternative_cost": self.effective_alternative_cost,
            "policy_support": self.policy_support,
            "mandate_share": self.mandate_share,
            "peer_influence": self.peer_influence,
        }
