from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from navaero_transition_model.core.agent_types import AviationPassengerAirlineAgent
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import NATMScenario


def _append_ambiguity_config(scenario_yaml: Path) -> None:
    (scenario_yaml.parent / "ambiguity_probabilities.csv").write_text(
        """scenario,Base,Stress
baseline,0.6,0.4
high_fuel_price,0.4,0.6
""",
        encoding="utf-8",
    )
    scenario_yaml.write_text(
        scenario_yaml.read_text(encoding="utf-8")
        + """

ambiguity_aware_decision:
  enabled: true
  scenario_ids:
    - baseline
    - high_fuel_price
  probability_table: ambiguity_probabilities.csv
  tail_alpha: 0.8
""",
        encoding="utf-8",
    )


def _prepare_case(
    tmp_path: Path,
    *,
    decision_attitude: str,
    decision_mode: str | None,
) -> Path:
    source_dir = Path(__file__).resolve().parents[1] / "data" / "input" / "baseline-passenger-transition"
    case_dir = tmp_path / "baseline-passenger-transition"
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / "aviation_fleet_stock.csv"
    fleet = pd.read_csv(fleet_path).head(1).copy()
    fleet["investment_logic"] = "ambiguity_aware_utility"
    fleet["decision_attitude"] = decision_attitude
    if decision_mode is not None:
        fleet["decision_mode"] = decision_mode
    fleet["Age (Years)"] = 35.0
    fleet.to_csv(fleet_path, index=False)

    _append_ambiguity_config(case_dir / "scenario.yaml")
    return case_dir


def _resolved_decision_mode(case_dir: Path) -> set[str]:
    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    model = NATMModel(scenario, seed=42)
    agent = model.get_sector_agents("aviation")[0]
    aircraft = agent.fleet.frame.iloc[0]
    agent.decision_logic.select_technology_for_aircraft(
        agent,
        aircraft,
        scenario.start_year,
        initial_ets_balance=agent.remaining_ets_allowance,
    )
    scores = model.to_ambiguity_decision_scores_frame()
    return set(scores["decision_mode"].unique())


def test_explicit_decision_mode_overrides_decision_attitude(tmp_path: Path) -> None:
    case_dir = _prepare_case(
        tmp_path,
        decision_attitude="risk_neutral",
        decision_mode="risk_averse_expected_shortfall",
    )

    assert _resolved_decision_mode(case_dir) == {"risk_averse_expected_shortfall"}


@pytest.mark.parametrize(
    ("decision_attitude", "expected_mode"),
    [
        ("risk_neutral", "risk_neutral"),
        ("risk_averse_mean", "risk_averse_mean"),
        ("risk_averse_expected_shortfall", "risk_averse_expected_shortfall"),
        ("risk_averse", "risk_averse_expected_shortfall"),
        ("ambiguity_averse", "risk_averse_expected_shortfall"),
    ],
)
def test_blank_decision_mode_derives_from_decision_attitude(
    tmp_path: Path,
    decision_attitude: str,
    expected_mode: str,
) -> None:
    case_dir = _prepare_case(tmp_path, decision_attitude=decision_attitude, decision_mode=None)

    assert _resolved_decision_mode(case_dir) == {expected_mode}


@pytest.mark.parametrize(
    ("fleet_filename", "case_name", "label"),
    [
        ("aviation_fleet_stock.csv", "baseline-passenger-transition", "aviation"),
        ("maritime_fleet_stock.csv", "baseline-maritime-cargo-transition", "maritime cargo"),
    ],
)
def test_invalid_decision_mode_fails_fast_at_load(
    tmp_path: Path,
    fleet_filename: str,
    case_name: str,
    label: str,
) -> None:
    source_dir = Path(__file__).resolve().parents[1] / "data" / "input" / case_name
    case_dir = tmp_path / case_name
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / fleet_filename
    fleet = pd.read_csv(fleet_path)
    fleet["decision_mode"] = "not_a_real_mode"
    fleet.to_csv(fleet_path, index=False)

    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    with pytest.raises(ValueError, match=f"Unsupported {label} decision_mode values"):
        NATMModel(scenario, seed=42)


def test_decision_mode_round_trips_into_outputs(tmp_path: Path) -> None:
    case_dir = _prepare_case(
        tmp_path,
        decision_attitude="risk_neutral",
        decision_mode="risk_averse_mean",
    )
    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    model = NATMModel(scenario, seed=42)

    model.run()

    aircraft_summary = model.to_aircraft_frame()
    agent_summary = model.to_agent_frame()
    assert "decision_mode" in aircraft_summary.columns
    assert "decision_mode" in agent_summary.columns
    assert set(aircraft_summary["decision_mode"].unique()) == {"risk_averse_mean"}
    assert set(agent_summary["decision_mode"].unique()) == {"risk_averse_mean"}


def test_default_decision_mode_is_blank_when_column_absent() -> None:
    scenario = NATMScenario.from_yaml(
        Path(__file__).resolve().parents[1]
        / "data" / "input" / "baseline-passenger-transition"
        / "scenario.yaml",
    )
    model = NATMModel(scenario, seed=42)

    assert all(
        agent.decision_mode == ""
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
    )
