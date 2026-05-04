from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from navaero_transition_model.core.case_inputs.scenario_table import ScenarioTable
from navaero_transition_model.core.decision_logic import (
    LegacyWeightedUtilityCargoLogic,
    LegacyWeightedUtilityLogic,
    LegacyWeightedUtilityMaritimeCargoLogic,
    LegacyWeightedUtilityMaritimePassengerLogic,
    build_aviation_cargo_decision_logic,
    build_aviation_passenger_decision_logic,
    build_maritime_cargo_decision_logic,
    build_maritime_passenger_decision_logic,
)
from navaero_transition_model.core.decision_logic.ambiguity_aware_utility import (
    AmbiguityAwareCargoLogic,
    AmbiguityAwareMaritimeCargoLogic,
    AmbiguityAwareMaritimePassengerLogic,
    AmbiguityAwareUtilityLogic,
    ScenarioCandidateOutcome,
)
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import (
    AmbiguityAwareDecisionConfig,
    NATMScenario,
)


def _scenario_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults = {
        "variable_group": "policy",
        "country": "",
        "operator_name": "",
        "segment": "",
        "technology_name": "",
        "primary_energy_carrier": "",
        "secondary_energy_carrier": "",
        "saf_pathway": "",
        "unit": "",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _append_ambiguity_config(scenario_yaml: Path) -> None:
    scenario_yaml.write_text(
        scenario_yaml.read_text(encoding="utf-8")
        + """

ambiguity_aware_decision:
  enabled: true
  scenario_ids:
    - baseline
    - high_fuel_price
  probabilities:
    baseline: 0.6
    high_fuel_price: 0.4
  ambiguity:
    enabled: false
    probability_deviation: 0.0
  expected_shortfall_alpha: 0.5
  robust_metric: worst_case_expected_utility
""",
        encoding="utf-8",
    )


def test_scenario_table_defaults_missing_scenario_id_to_baseline() -> None:
    table = ScenarioTable(
        _scenario_frame(
            [
                {"variable_name": "carbon_price", "2025": 40.0},
            ],
        ),
    )

    assert table.value("carbon_price", 2025) == 40.0
    assert table.value("carbon_price", 2025, scenario_id="baseline") == 40.0
    assert table.value("carbon_price", 2025, scenario_id="high_fuel_price") == 40.0


def test_scenario_table_returns_scenario_specific_values() -> None:
    table = ScenarioTable(
        _scenario_frame(
            [
                {"scenario_id": "baseline", "variable_name": "carbon_price", "2025": 40.0},
                {
                    "scenario_id": "high_carbon_price",
                    "variable_name": "carbon_price",
                    "2025": 120.0,
                },
            ],
        ),
    )

    assert table.value("carbon_price", 2025) == 40.0
    assert table.value("carbon_price", 2025, scenario_id="high_carbon_price") == 120.0


def test_scenario_table_falls_back_to_baseline_when_scenario_scope_is_missing() -> None:
    table = ScenarioTable(
        _scenario_frame(
            [
                {"scenario_id": "baseline", "variable_name": "carbon_price", "2025": 40.0},
                {
                    "scenario_id": "high_carbon_price",
                    "variable_name": "carbon_price",
                    "country": "Germany",
                    "2025": 120.0,
                },
            ],
        ),
    )

    assert (
        table.value("carbon_price", 2025, scenario_id="high_carbon_price", country="Germany")
        == 120.0
    )
    assert (
        table.value("carbon_price", 2025, scenario_id="high_carbon_price", country="France") == 40.0
    )


def test_ambiguity_config_normalizes_probability_sum() -> None:
    with pytest.warns(RuntimeWarning, match="normalizing"):
        config = AmbiguityAwareDecisionConfig.from_dict(
            {
                "enabled": True,
                "scenario_ids": ["baseline", "stress"],
                "probabilities": {"baseline": 2.0, "stress": 1.0},
            },
        )

    assert config.enabled
    assert config.probabilities["baseline"] == pytest.approx(2.0 / 3.0)
    assert config.probabilities["stress"] == pytest.approx(1.0 / 3.0)


def test_ambiguity_config_defaults_to_worst_case_expected_shortfall() -> None:
    config = AmbiguityAwareDecisionConfig.from_dict(
        {
            "enabled": True,
            "scenario_ids": ["baseline", "stress"],
            "probabilities": {"baseline": 0.5, "stress": 0.5},
        },
    )

    assert config.robust_metric == "worst_case_expected_shortfall"


def test_ambiguity_config_accepts_worst_case_expected_utility() -> None:
    config = AmbiguityAwareDecisionConfig.from_dict(
        {
            "enabled": True,
            "scenario_ids": ["baseline", "stress"],
            "probabilities": {"baseline": 0.5, "stress": 0.5},
            "robust_metric": "worst_case_expected_utility",
        },
    )

    assert config.robust_metric == "worst_case_expected_utility"


def _dummy_agent(
    decision_attitude: str,
    *,
    delta: float = 0.0,
    robust_metric: str = "worst_case_expected_shortfall",
) -> SimpleNamespace:
    config = AmbiguityAwareDecisionConfig(
        enabled=True,
        scenario_ids=("baseline", "stress"),
        probabilities={"baseline": 0.5, "stress": 0.5},
        ambiguity_enabled=delta > 0.0,
        probability_deviation=delta,
        expected_shortfall_alpha=0.5,
        robust_metric=robust_metric,
    )
    return SimpleNamespace(
        decision_attitude=decision_attitude,
        model=SimpleNamespace(scenario=SimpleNamespace(ambiguity_aware_decision=config)),
    )


def _aggregate(
    logic: AmbiguityAwareUtilityLogic,
    agent: SimpleNamespace,
    technology_name: str,
    baseline_score: float,
    stress_score: float,
):
    return logic._candidate_aggregate(
        agent,
        pd.Series({"technology_name": technology_name}),
        (
            ScenarioCandidateOutcome("baseline", 0.5, baseline_score, None),
            ScenarioCandidateOutcome("stress", 0.5, stress_score, None),
        ),
    )


def _aggregate_score(
    logic: AmbiguityAwareUtilityLogic,
    agent: SimpleNamespace,
    technology_name: str,
    baseline_score: float,
    stress_score: float,
) -> float:
    aggregate = _aggregate(logic, agent, technology_name, baseline_score, stress_score)
    return aggregate.robust_score


def test_risk_neutral_score_uses_expected_utility() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent("risk_neutral")

    high_mean = _aggregate_score(logic, agent, "high_mean", 0.9, 0.3)
    stable = _aggregate_score(logic, agent, "stable", 0.5, 0.5)

    assert high_mean > stable


def test_risk_averse_score_uses_lower_tail_utility() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent("risk_averse")

    downside_heavy = _aggregate_score(logic, agent, "downside_heavy", 1.0, 0.0)
    stable = _aggregate_score(logic, agent, "stable", 0.55, 0.55)

    assert stable > downside_heavy


def test_ambiguity_averse_score_uses_worst_case_probability_bounds() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent("ambiguity_averse", delta=0.25)

    upside_heavy = _aggregate_score(logic, agent, "upside_heavy", 1.0, 0.1)
    stable = _aggregate_score(logic, agent, "stable", 0.5, 0.5)

    assert stable > upside_heavy


def test_ambiguity_averse_defaults_to_worst_case_expected_shortfall() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent("ambiguity_averse", delta=0.25)

    aggregate = _aggregate(logic, agent, "upside_heavy", 1.0, 0.1)

    assert aggregate.robust_score == pytest.approx(
        aggregate.worst_case_expected_shortfall_utility,
    )
    assert aggregate.robust_score < aggregate.worst_case_utility


def test_ambiguity_averse_can_use_explicit_worst_case_expected_utility() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent(
        "ambiguity_averse",
        delta=0.25,
        robust_metric="worst_case_expected_utility",
    )

    aggregate = _aggregate(logic, agent, "upside_heavy", 1.0, 0.1)

    assert aggregate.robust_score == pytest.approx(aggregate.worst_case_utility)


def test_unavailable_adverse_scenario_reduces_expected_shortfall_scores() -> None:
    logic = AmbiguityAwareUtilityLogic()
    agent = _dummy_agent("ambiguity_averse", delta=0.25)
    unavailable_stress_outcome = ScenarioCandidateOutcome("stress", 0.5, 0.0, None)

    stable = logic._candidate_aggregate(
        agent,
        pd.Series({"technology_name": "stable"}),
        (
            ScenarioCandidateOutcome("baseline", 0.5, 0.6, None),
            ScenarioCandidateOutcome("stress", 0.5, 0.6, None),
        ),
    )
    unavailable_in_stress = logic._candidate_aggregate(
        agent,
        pd.Series({"technology_name": "unavailable_in_stress"}),
        (
            ScenarioCandidateOutcome("baseline", 0.5, 1.0, None),
            unavailable_stress_outcome,
        ),
    )

    assert unavailable_stress_outcome.score == 0.0
    assert unavailable_stress_outcome.evaluation is None
    assert unavailable_in_stress.expected_shortfall_utility == pytest.approx(0.0)
    assert unavailable_in_stress.worst_case_expected_shortfall_utility == pytest.approx(0.0)
    assert stable.expected_shortfall_utility > unavailable_in_stress.expected_shortfall_utility
    assert (
        stable.worst_case_expected_shortfall_utility
        > unavailable_in_stress.worst_case_expected_shortfall_utility
    )


@pytest.mark.parametrize(
    ("builder", "logic_name", "logic_class"),
    [
        (
            build_aviation_passenger_decision_logic,
            "ambiguity_aware_utility",
            AmbiguityAwareUtilityLogic,
        ),
        (
            build_aviation_cargo_decision_logic,
            "ambiguity_aware_utility",
            AmbiguityAwareCargoLogic,
        ),
        (
            build_maritime_cargo_decision_logic,
            "ambiguity_aware_utility",
            AmbiguityAwareMaritimeCargoLogic,
        ),
        (
            build_maritime_passenger_decision_logic,
            "ambiguity_aware_utility",
            AmbiguityAwareMaritimePassengerLogic,
        ),
    ],
)
def test_ambiguity_aware_logic_plugins_are_registered(builder, logic_name, logic_class) -> None:
    logic = builder(logic_name)

    assert isinstance(logic, logic_class)
    assert logic.name == "ambiguity_aware_utility"


@pytest.mark.parametrize(
    ("builder", "logic_alias", "logic_class"),
    [
        (
            build_aviation_cargo_decision_logic,
            "ambiguity_aware_utility_cargo",
            AmbiguityAwareCargoLogic,
        ),
        (
            build_maritime_cargo_decision_logic,
            "ambiguity_aware_utility_maritime_cargo",
            AmbiguityAwareMaritimeCargoLogic,
        ),
        (
            build_maritime_passenger_decision_logic,
            "ambiguity_aware_utility_maritime_passenger",
            AmbiguityAwareMaritimePassengerLogic,
        ),
    ],
)
def test_sector_specific_ambiguity_names_remain_aliases(
    builder,
    logic_alias,
    logic_class,
) -> None:
    assert isinstance(builder(logic_alias), logic_class)


@pytest.mark.parametrize(
    ("builder", "logic_class"),
    [
        (build_aviation_passenger_decision_logic, LegacyWeightedUtilityLogic),
        (build_aviation_cargo_decision_logic, LegacyWeightedUtilityCargoLogic),
        (build_maritime_cargo_decision_logic, LegacyWeightedUtilityMaritimeCargoLogic),
        (build_maritime_passenger_decision_logic, LegacyWeightedUtilityMaritimePassengerLogic),
    ],
)
def test_legacy_weighted_utility_name_works_for_all_sectors(builder, logic_class) -> None:
    logic = builder("legacy_weighted_utility")

    assert isinstance(logic, logic_class)
    assert logic.name == "legacy_weighted_utility"


@pytest.mark.parametrize(
    ("builder", "legacy_alias", "logic_class"),
    [
        (
            build_aviation_cargo_decision_logic,
            "legacy_weighted_utility_cargo",
            LegacyWeightedUtilityCargoLogic,
        ),
        (
            build_maritime_cargo_decision_logic,
            "legacy_weighted_utility_maritime_cargo",
            LegacyWeightedUtilityMaritimeCargoLogic,
        ),
        (
            build_maritime_passenger_decision_logic,
            "legacy_weighted_utility_maritime_passenger",
            LegacyWeightedUtilityMaritimePassengerLogic,
        ),
    ],
)
def test_sector_specific_legacy_names_remain_aliases(builder, legacy_alias, logic_class) -> None:
    assert isinstance(builder(legacy_alias), logic_class)


def test_aviation_passenger_ambiguity_logic_writes_robust_frontier(tmp_path: Path) -> None:
    source_dir = Path(__file__).resolve().parents[1] / "data" / "baseline-passenger-transition"
    case_dir = tmp_path / "baseline-passenger-transition"
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / "aviation_fleet_stock.csv"
    fleet = pd.read_csv(fleet_path).head(1).copy()
    fleet["investment_logic"] = "ambiguity_aware_utility"
    fleet["decision_attitude"] = "risk_neutral"
    fleet["Age (Years)"] = 35.0
    fleet.to_csv(fleet_path, index=False)

    technology_path = case_dir / "aviation_technology_catalog.csv"
    technology_catalog = pd.read_csv(technology_path)
    technology_catalog["lifetime_years"] = 2
    technology_catalog.to_csv(technology_path, index=False)

    scenario_yaml = case_dir / "scenario.yaml"
    _append_ambiguity_config(scenario_yaml)

    scenario = NATMScenario.from_yaml(scenario_yaml)
    model = NATMModel(scenario, seed=42)
    agent = model.get_sector_agents("aviation")[0]
    aircraft = agent.fleet.frame.iloc[0]
    agent.decision_logic.select_technology_for_aircraft(
        agent,
        aircraft,
        scenario.start_year,
        initial_ets_balance=agent.remaining_ets_allowance,
    )

    frontier = model.to_aviation_robust_frontier_frame()
    assert not frontier.empty
    assert {
        "year",
        "application_name",
        "decision_attitude",
        "candidate_technology",
        "scenario_id",
        "candidate_utility",
        "candidate_economic_utility",
        "expected_utility",
        "robust_score",
        "worst_case_utility",
        "worst_case_expected_shortfall_utility",
        "selected_flag",
    }.issubset(frontier.columns)
    assert set(frontier["scenario_id"].unique()) == {"baseline", "high_fuel_price"}
    assert frontier["selected_flag"].any()
    assert {"risk_neutral"} == set(model.to_agent_frame()["decision_attitude"].unique())


@pytest.mark.parametrize(
    (
        "case_name",
        "fleet_filename",
        "technology_filename",
        "logic_name",
        "sector_name",
        "selection_method",
        "frontier_method",
    ),
    [
        (
            "baseline-cargo-transition",
            "aviation_fleet_stock.csv",
            "aviation_technology_catalog.csv",
            "ambiguity_aware_utility",
            "aviation",
            "select_technology_for_aircraft",
            "to_aviation_robust_frontier_frame",
        ),
        (
            "baseline-maritime-cargo-transition",
            "maritime_fleet_stock.csv",
            "maritime_technology_catalog.csv",
            "ambiguity_aware_utility",
            "maritime",
            "select_technology_for_vessel",
            "to_maritime_robust_frontier_frame",
        ),
        (
            "baseline-maritime-passenger-transition",
            "maritime_fleet_stock.csv",
            "maritime_technology_catalog.csv",
            "ambiguity_aware_utility",
            "maritime",
            "select_technology_for_vessel",
            "to_maritime_robust_frontier_frame",
        ),
    ],
)
def test_generalized_ambiguity_logic_writes_robust_frontier(
    tmp_path: Path,
    case_name: str,
    fleet_filename: str,
    technology_filename: str,
    logic_name: str,
    sector_name: str,
    selection_method: str,
    frontier_method: str,
) -> None:
    source_dir = Path(__file__).resolve().parents[1] / "data" / case_name
    case_dir = tmp_path / case_name
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / fleet_filename
    fleet = pd.read_csv(fleet_path).head(1).copy()
    fleet["investment_logic"] = logic_name
    fleet["decision_attitude"] = "risk_averse"
    fleet["Age (Years)"] = 35.0
    fleet.to_csv(fleet_path, index=False)

    technology_path = case_dir / technology_filename
    technology_catalog = pd.read_csv(technology_path)
    technology_catalog["lifetime_years"] = 2
    technology_catalog.to_csv(technology_path, index=False)

    scenario_yaml = case_dir / "scenario.yaml"
    _append_ambiguity_config(scenario_yaml)

    scenario = NATMScenario.from_yaml(scenario_yaml)
    model = NATMModel(scenario, seed=42)
    agent = model.get_sector_agents(sector_name)[0]
    asset = agent.fleet.frame.iloc[0]
    getattr(agent.decision_logic, selection_method)(
        agent,
        asset,
        scenario.start_year,
        initial_ets_balance=agent.remaining_ets_allowance,
    )

    frontier = getattr(model, frontier_method)()
    assert not frontier.empty
    assert {logic_name} == set(model.to_agent_frame()["investment_logic"].unique())
    assert {"risk_averse"} == set(model.to_agent_frame()["decision_attitude"].unique())
    assert set(frontier["scenario_id"].unique()) == {"baseline", "high_fuel_price"}
    assert frontier["selected_flag"].any()
