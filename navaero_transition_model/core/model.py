from __future__ import annotations

from dataclasses import asdict, dataclass

import mesa
import pandas as pd

from navaero_transition_model.core.agent_types import (
    AviationCargoAirlineAgent,
    AviationOperatorAgent,
    AviationPassengerAirlineAgent,
    MaritimeCargoShiplineAgent,
    MaritimeOperatorAgent,
    MaritimePassengerShiplineAgent,
    SectorMarketContext,
)
from navaero_transition_model.core.environment import TransitionEnvironment
from navaero_transition_model.core.loaders import (
    load_aviation_cargo_case,
    load_aviation_passenger_case,
    load_maritime_cargo_case,
    load_maritime_passenger_case,
)
from navaero_transition_model.core.policy import PolicySignal, SectorPolicySignal
from navaero_transition_model.core.result_exports import (
    AircraftStockExporter,
    AviationEnergyEmissionsExporter,
    AviationInvestmentExporter,
    AviationTechnologyExporter,
    MaritimeEnergyEmissionsExporter,
    MaritimeInvestmentExporter,
    MaritimeTechnologyExporter,
)
from navaero_transition_model.core.scenario import NATMScenario


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


@dataclass
class YearSnapshot:
    year: int
    carbon_price: float
    environment_aviation_infrastructure: float
    environment_maritime_infrastructure: float
    environment_policy_alignment: float
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

    default_sector_agent_classes = {
        "aviation": [AviationOperatorAgent],
        "maritime": [MaritimeOperatorAgent],
    }

    def __init__(self, scenario: NATMScenario, *, seed: int | None = None) -> None:
        super().__init__(seed=seed)
        self.scenario = scenario
        self.enabled_sectors = scenario.enabled_sectors
        self.sector_agent_classes = {
            sector_name: list(agent_classes)
            for sector_name, agent_classes in self.default_sector_agent_classes.items()
        }
        self.environment = TransitionEnvironment.from_csvs(
            countries_path=scenario.environment_input_path("countries"),
            corridors_path=scenario.environment_input_path("corridors"),
        )
        self.aviation_passenger_inputs = None
        self.aviation_cargo_inputs = None
        self.maritime_cargo_inputs = None
        self.maritime_passenger_inputs = None

        for sector_name in self.enabled_sectors:
            if sector_name == "aviation":
                created_any = False
                if self._has_aviation_passenger_case_inputs():
                    self._create_aviation_passenger_agents()
                    created_any = True
                if self._has_aviation_cargo_case_inputs():
                    self._create_aviation_cargo_agents()
                    created_any = True
                if created_any:
                    continue
            if sector_name == "maritime":
                created_any = False
                if self._has_maritime_passenger_case_inputs():
                    self._create_maritime_passenger_agents()
                    created_any = True
                if self._has_maritime_cargo_case_inputs():
                    self._create_maritime_cargo_agents()
                    created_any = True
                if created_any:
                    continue
            raise NotImplementedError(
                "This NATM configuration currently expects a case-defined sector/application "
                "setup with the standard CSV files in the case folder.",
            )
        for agent in self.agents:
            self.environment.ensure_country(agent.operator_country)

        self.current_sector_context = self._build_sector_context()
        self._aircraft_history_frames: list[pd.DataFrame] = []
        self.datacollector = mesa.DataCollector(
            model_reporters={
                "year": "current_year",
                "carbon_price": lambda m: m.current_policy_signal.carbon_price,
                "environment_aviation_infrastructure": lambda m: m.environment_average(
                    "aviation_infrastructure",
                ),
                "environment_maritime_infrastructure": lambda m: m.environment_average(
                    "maritime_infrastructure",
                ),
                "environment_policy_alignment": lambda m: m.environment_average(
                    "policy_alignment",
                ),
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
                "operator_country": "operator_country",
                "sector_name": "sector_name",
                "application_name": lambda agent: getattr(agent, "application_name", ""),
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
                "investment_logic": lambda agent: getattr(agent, "investment_logic_name", ""),
            },
        )

        self.history = [self._snapshot()]
        self.datacollector.collect(self)
        self._record_detailed_outputs()

    @property
    def current_year(self) -> int:
        return self.scenario.start_year + self.steps

    @property
    def current_policy_signal(self):
        if (
            self.aviation_passenger_inputs is not None
            or self.aviation_cargo_inputs is not None
            or self.maritime_cargo_inputs is not None
            or self.maritime_passenger_inputs is not None
        ):
            aviation_carbon_price = self._aviation_scenario_value(
                "carbon_price",
                self.current_year,
                default=None,
            )
            maritime_carbon_price = self._maritime_scenario_value(
                "carbon_tax",
                self.current_year,
                default=None,
            )
            if maritime_carbon_price is None:
                maritime_carbon_price = self._maritime_scenario_value(
                    "carbon_price",
                    self.current_year,
                    default=None,
                )
            carbon_candidates = [
                float(value)
                for value in (aviation_carbon_price, maritime_carbon_price)
                if value is not None
            ]
            carbon_price = max(carbon_candidates) if carbon_candidates else 0.0

            aviation_clean_fuel_subsidy = self._aviation_scenario_value(
                "clean_fuel_subsidy",
                self.current_year,
                default=0.0,
            )
            aviation_adoption_mandate = self._aviation_scenario_value(
                "adoption_mandate",
                self.current_year,
                default=0.0,
            )
            maritime_clean_fuel_subsidy = self._maritime_scenario_value(
                "clean_fuel_subsidy",
                self.current_year,
                default=0.0,
            )
            maritime_adoption_mandate = self._maritime_scenario_value(
                "biofuel_mandate",
                self.current_year,
                default=None,
            )
            if maritime_adoption_mandate is None:
                maritime_adoption_mandate = self._maritime_scenario_value(
                    "adoption_mandate",
                    self.current_year,
                    default=0.0,
                )
            return PolicySignal(
                carbon_price=float(carbon_price),
                aviation=SectorPolicySignal(
                    clean_fuel_subsidy=float(aviation_clean_fuel_subsidy or 0.0),
                    adoption_mandate=float(aviation_adoption_mandate or 0.0),
                ),
                maritime=SectorPolicySignal(
                    clean_fuel_subsidy=float(maritime_clean_fuel_subsidy or 0.0),
                    adoption_mandate=float(maritime_adoption_mandate or 0.0),
                ),
            )
        return PolicySignal(
            carbon_price=0.0,
            aviation=SectorPolicySignal(clean_fuel_subsidy=0.0, adoption_mandate=0.0),
            maritime=SectorPolicySignal(clean_fuel_subsidy=0.0, adoption_mandate=0.0),
        )

    def get_sector_agents(self, sector_name: str):
        sector_agents: list[object] = []
        for agent_class in self.sector_agent_classes.get(sector_name, []):
            try:
                sector_agents.extend(list(self.agents_by_type[agent_class]))
            except KeyError:
                continue
        return sector_agents

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

    def environment_average(self, attribute: str) -> float:
        return _mean([getattr(state, attribute) for state in self.environment.countries.values()])

    def _has_aviation_passenger_case_inputs(self) -> bool:
        if not self.scenario.is_sector_enabled("aviation"):
            return False
        if not self.scenario.is_application_enabled("aviation", "passenger"):
            return False
        case_path = self.scenario.base_path
        required_files = (
            case_path / "aviation_fleet_stock.csv",
            case_path / "aviation_technology_catalog.csv",
            case_path / "aviation_scenario.csv",
        )
        return all(path.exists() for path in required_files)

    def _has_aviation_cargo_case_inputs(self) -> bool:
        if not self.scenario.is_sector_enabled("aviation"):
            return False
        if not self.scenario.is_application_enabled("aviation", "cargo"):
            return False
        case_path = self.scenario.base_path
        required_files = (
            case_path / "aviation_fleet_stock.csv",
            case_path / "aviation_technology_catalog.csv",
            case_path / "aviation_scenario.csv",
        )
        return all(path.exists() for path in required_files)

    def _has_maritime_cargo_case_inputs(self) -> bool:
        if not self.scenario.is_sector_enabled("maritime"):
            return False
        if not self.scenario.is_application_enabled("maritime", "cargo"):
            return False
        case_path = self.scenario.base_path
        required_files = (
            case_path / "maritime_fleet_stock.csv",
            case_path / "maritime_technology_catalog.csv",
            case_path / "maritime_scenario.csv",
        )
        return all(path.exists() for path in required_files)

    def _has_maritime_passenger_case_inputs(self) -> bool:
        if not self.scenario.is_sector_enabled("maritime"):
            return False
        if not self.scenario.is_application_enabled("maritime", "passenger"):
            return False
        case_path = self.scenario.base_path
        required_files = (
            case_path / "maritime_fleet_stock.csv",
            case_path / "maritime_technology_catalog.csv",
            case_path / "maritime_scenario.csv",
        )
        return all(path.exists() for path in required_files)

    def _register_sector_agent_class(self, sector_name: str, agent_class: type) -> None:
        sector_classes = self.sector_agent_classes.setdefault(sector_name, [])
        if agent_class not in sector_classes:
            sector_classes.append(agent_class)

    def _create_aviation_passenger_agents(self) -> None:
        self.aviation_passenger_inputs = load_aviation_passenger_case(self.scenario.base_path)
        self.aviation_passenger_inputs.validate_capacity_planning_inputs(
            self.scenario.start_year,
            self.scenario.end_year,
        )
        self._register_sector_agent_class("aviation", AviationPassengerAirlineAgent)
        grouped_fleet = self.aviation_passenger_inputs.grouped_operator_fleet()
        for (operator_name, operator_country), fleet_df in grouped_fleet:
            AviationPassengerAirlineAgent(
                self,
                operator_name=operator_name,
                operator_country=operator_country,
                fleet_frame=fleet_df,
                technology_catalog=self.aviation_passenger_inputs.technology_catalog,
                scenario_table=self.aviation_passenger_inputs.scenario_table,
            )

    def _create_aviation_cargo_agents(self) -> None:
        self.aviation_cargo_inputs = load_aviation_cargo_case(self.scenario.base_path)
        self.aviation_cargo_inputs.validate_capacity_planning_inputs(
            self.scenario.start_year,
            self.scenario.end_year,
        )
        self._register_sector_agent_class("aviation", AviationCargoAirlineAgent)
        grouped_fleet = self.aviation_cargo_inputs.grouped_operator_fleet()
        for (operator_name, operator_country), fleet_df in grouped_fleet:
            AviationCargoAirlineAgent(
                self,
                operator_name=operator_name,
                operator_country=operator_country,
                fleet_frame=fleet_df,
                technology_catalog=self.aviation_cargo_inputs.technology_catalog,
                scenario_table=self.aviation_cargo_inputs.scenario_table,
            )

    def _create_maritime_cargo_agents(self) -> None:
        self.maritime_cargo_inputs = load_maritime_cargo_case(self.scenario.base_path)
        self.maritime_cargo_inputs.validate_capacity_planning_inputs(
            self.scenario.start_year,
            self.scenario.end_year,
        )
        self._register_sector_agent_class("maritime", MaritimeCargoShiplineAgent)
        grouped_fleet = self.maritime_cargo_inputs.grouped_operator_fleet()
        for (operator_name, operator_country), fleet_df in grouped_fleet:
            MaritimeCargoShiplineAgent(
                self,
                operator_name=operator_name,
                operator_country=operator_country,
                fleet_frame=fleet_df,
                technology_catalog=self.maritime_cargo_inputs.technology_catalog,
                scenario_table=self.maritime_cargo_inputs.scenario_table,
            )

    def _create_maritime_passenger_agents(self) -> None:
        self.maritime_passenger_inputs = load_maritime_passenger_case(self.scenario.base_path)
        self.maritime_passenger_inputs.validate_capacity_planning_inputs(
            self.scenario.start_year,
            self.scenario.end_year,
        )
        self._register_sector_agent_class("maritime", MaritimePassengerShiplineAgent)
        grouped_fleet = self.maritime_passenger_inputs.grouped_operator_fleet()
        for (operator_name, operator_country), fleet_df in grouped_fleet:
            MaritimePassengerShiplineAgent(
                self,
                operator_name=operator_name,
                operator_country=operator_country,
                fleet_frame=fleet_df,
                technology_catalog=self.maritime_passenger_inputs.technology_catalog,
                scenario_table=self.maritime_passenger_inputs.scenario_table,
            )

    def _aviation_scenario_value(
        self,
        variable_name: str,
        year: int,
        *,
        default: float | None = None,
        **scope: str,
    ) -> float | None:
        scenario_tables = []
        if self.aviation_passenger_inputs is not None:
            scenario_tables.append(self.aviation_passenger_inputs.scenario_table)
        if self.aviation_cargo_inputs is not None:
            scenario_tables.append(self.aviation_cargo_inputs.scenario_table)
        for scenario_table in scenario_tables:
            value = scenario_table.value(variable_name, year, default=None, **scope)
            if value is not None:
                return value
        return default

    def _maritime_scenario_value(
        self,
        variable_name: str,
        year: int,
        *,
        default: float | None = None,
        **scope: str,
    ) -> float | None:
        scenario_tables = []
        if self.maritime_passenger_inputs is not None:
            scenario_tables.append(self.maritime_passenger_inputs.scenario_table)
        if self.maritime_cargo_inputs is not None:
            scenario_tables.append(self.maritime_cargo_inputs.scenario_table)
        for scenario_table in scenario_tables:
            value = scenario_table.value(variable_name, year, default=None, **scope)
            if value is not None:
                return value
        return default

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
            environment_aviation_infrastructure=self.environment_average(
                "aviation_infrastructure",
            ),
            environment_maritime_infrastructure=self.environment_average(
                "maritime_infrastructure",
            ),
            environment_policy_alignment=self.environment_average("policy_alignment"),
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

    def _record_detailed_outputs(self) -> None:
        aviation_agents = list(self.get_sector_agents("aviation"))

        detailed_agents = [
            agent
            for agent in aviation_agents
            if isinstance(agent, (AviationPassengerAirlineAgent, AviationCargoAirlineAgent))
        ]
        maritime_agents = list(self.get_sector_agents("maritime"))
        detailed_agents.extend(
            agent
            for agent in maritime_agents
            if isinstance(agent, (MaritimeCargoShiplineAgent, MaritimePassengerShiplineAgent))
        )
        if not detailed_agents:
            return

        yearly_snapshots = [agent.fleet_snapshot(self.current_year) for agent in detailed_agents]
        self._aircraft_history_frames.append(
            pd.concat(yearly_snapshots, ignore_index=True),
        )

    def step(self) -> None:
        if self.current_year > self.scenario.end_year:
            self.running = False
            return

        self.current_sector_context = self._build_sector_context()
        for sector_name in self.enabled_sectors:
            sector_agents = self.get_sector_agents(sector_name)
            if hasattr(sector_agents, "shuffle_do"):
                sector_agents.shuffle_do("step")
            else:
                for agent in sector_agents:
                    agent.step()
        self.environment.update(self.current_policy_signal, list(self.agents))

        self.history.append(self._snapshot())
        self.datacollector.collect(self)
        self._record_detailed_outputs()

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

    def to_aircraft_frame(self) -> pd.DataFrame:
        return AircraftStockExporter().export(self)

    def to_aviation_technology_frame(self) -> pd.DataFrame:
        return AviationTechnologyExporter().export(self)

    def to_aviation_energy_emissions_frame(self) -> pd.DataFrame:
        return AviationEnergyEmissionsExporter().export(self)

    def to_aviation_investment_frame(self) -> pd.DataFrame:
        return AviationInvestmentExporter().export(self)

    def to_maritime_technology_frame(self) -> pd.DataFrame:
        return MaritimeTechnologyExporter().export(self)

    def to_maritime_energy_emissions_frame(self) -> pd.DataFrame:
        return MaritimeEnergyEmissionsExporter().export(self)

    def to_maritime_investment_frame(self) -> pd.DataFrame:
        return MaritimeInvestmentExporter().export(self)
