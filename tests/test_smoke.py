from pathlib import Path

from natm.core.model import NATMModel
from natm.core.scenario import NATMScenario


def test_default_scenario_runs_end_to_end() -> None:
    scenario_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    scenario = NATMScenario.from_yaml(scenario_path)
    model = NATMModel(scenario)

    history = model.run()

    assert len(history) == scenario.steps
    assert history[0].aviation_alternative_share < history[-1].aviation_alternative_share
    assert history[0].maritime_alternative_share < history[-1].maritime_alternative_share
