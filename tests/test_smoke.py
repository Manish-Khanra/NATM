from copy import deepcopy
from pathlib import Path

import mesa

from natm.core.agents import (
    AviationOperatorAgent,
    MaritimeOperatorAgent,
    TransportOperatorAgent,
)
from natm.core.model import NATMModel
from natm.core.scenario import NATMScenario


def load_default_scenario() -> NATMScenario:
    scenario_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    return NATMScenario.from_yaml(scenario_path)


def test_default_scenario_runs_end_to_end() -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)

    history = model.run()
    summary = model.to_frame()
    agent_summary = model.to_agent_frame()

    assert isinstance(model, mesa.Model)
    assert len(history) == scenario.steps
    assert len(model.agents) == scenario.aviation.operator_count + scenario.maritime.operator_count
    assert all(isinstance(agent, mesa.Agent) for agent in model.agents)
    assert all(isinstance(agent, TransportOperatorAgent) for agent in model.agents)
    assert len(model.agents_by_type[AviationOperatorAgent]) == scenario.aviation.operator_count
    assert len(model.agents_by_type[MaritimeOperatorAgent]) == scenario.maritime.operator_count
    assert history[0].aviation_alternative_share < history[-1].aviation_alternative_share
    assert history[0].maritime_alternative_share < history[-1].maritime_alternative_share
    assert summary["carbon_price"].iloc[0] < summary["carbon_price"].iloc[-1]
    assert "aviation_transition_pressure" in summary.columns
    assert "maritime_transition_pressure" in summary.columns
    assert {"aviation", "maritime"} == set(agent_summary["sector_name"].unique())
    assert agent_summary["operator_name"].nunique() == len(model.agents)


def test_stronger_policy_accelerates_adoption() -> None:
    baseline = load_default_scenario()
    stronger_policy = deepcopy(baseline)
    stronger_policy.policy.carbon_price.end = 260
    stronger_policy.policy.aviation.clean_fuel_subsidy.end = 0.35
    stronger_policy.policy.aviation.adoption_mandate.end = 0.42
    stronger_policy.policy.maritime.clean_fuel_subsidy.end = 0.30
    stronger_policy.policy.maritime.adoption_mandate.end = 0.46

    baseline_final = NATMModel(baseline, seed=42).run()[-1]
    stronger_final = NATMModel(stronger_policy, seed=42).run()[-1]

    assert stronger_final.aviation_alternative_share > baseline_final.aviation_alternative_share
    assert stronger_final.maritime_alternative_share > baseline_final.maritime_alternative_share
