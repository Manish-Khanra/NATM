from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from navaero_transition_model.core.agent_types import AviationPassengerAirlineAgent
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityLogic,
)
from navaero_transition_model.core.fleet_management import Fleet, planned_investments_from_fleet
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import InvestmentTimingConfig, NATMScenario

PASSENGER_CASE_NAME = "baseline-passenger-transition"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _passenger_case_dir() -> Path:
    return _repo_root() / "data" / PASSENGER_CASE_NAME


def _clone_case_directory(tmp_path: Path) -> Path:
    source_dir = _passenger_case_dir()
    case_dir = tmp_path / PASSENGER_CASE_NAME
    shutil.copytree(source_dir, case_dir)
    return case_dir


def _load_scenario(case_dir: Path) -> NATMScenario:
    return NATMScenario.from_yaml(case_dir / "scenario.yaml")


def test_investment_timing_defaults_preserve_todays_behavior() -> None:
    scenario = _load_scenario(_passenger_case_dir())

    assert scenario.investment_timing.include_continue_option is False
    assert scenario.investment_timing.residual_value_method == "none"


def test_investment_timing_config_rejects_unknown_residual_value_method() -> None:
    with pytest.raises(ValueError, match="residual_value_method"):
        InvestmentTimingConfig(residual_value_method="made_up_method")


def test_planned_investments_are_parsed_from_numbered_fleet_columns() -> None:
    fleet_frame = pd.DataFrame(
        {
            "aircraft_id": [1, 2],
            "planned_investment_1_year": [2030, pd.NA],
            "planned_investment_1_technology_name": ["drop_in_saf_medium", pd.NA],
            "planned_investment_1_technology_pattern": [pd.NA, pd.NA],
            "planned_investment_2_year": [2035, pd.NA],
            "planned_investment_2_technology_name": [pd.NA, pd.NA],
            "planned_investment_2_technology_pattern": ["hybrid_electric_*", pd.NA],
        },
    )

    planned = planned_investments_from_fleet(fleet_frame)

    assert len(planned) == 2
    assert set(planned["aircraft_id"]) == {1}
    first_event = planned.loc[planned["investment_year"] == 2030].iloc[0]
    assert first_event["technology_name"] == "drop_in_saf_medium"
    assert first_event["technology_pattern"] == ""
    second_event = planned.loc[planned["investment_year"] == 2035].iloc[0]
    assert second_event["technology_name"] == ""
    assert second_event["technology_pattern"] == "hybrid_electric_*"


def test_planned_investment_missing_technology_reference_fails_fast() -> None:
    fleet_frame = pd.DataFrame(
        {
            "aircraft_id": [1],
            "planned_investment_1_year": [2030],
        },
    )

    with pytest.raises(ValueError, match="requires a technology_name or technology_pattern"):
        planned_investments_from_fleet(fleet_frame)


def test_fleet_rejects_planned_investment_referencing_unknown_technology(tmp_path: Path) -> None:
    from navaero_transition_model.core.case_inputs import TechnologyCatalog
    from navaero_transition_model.core.case_inputs.aviation_passenger_case import (
        normalize_aviation_fleet_stock,
    )

    case_dir = _clone_case_directory(tmp_path)
    catalog = TechnologyCatalog.from_csv(case_dir / "aviation_technology_catalog.csv")
    fleet_path = case_dir / "aviation_fleet_stock.csv"
    fleet = pd.read_csv(fleet_path)
    fleet.loc[0, "planned_investment_1_year"] = 2030
    fleet.loc[0, "planned_investment_1_technology_name"] = "not_a_real_technology"
    fleet.to_csv(fleet_path, index=False)
    normalized = normalize_aviation_fleet_stock(fleet_path)

    with pytest.raises(ValueError, match="unknown technology_name"):
        Fleet(normalized, technology_catalog=catalog, start_year=2025)


def _make_young_aircraft_row(case_dir: Path, *, age_years: float = 2.0) -> tuple[Path, str]:
    """Pick one Lufthansa aircraft and make it clearly not due for replacement."""
    fleet_path = case_dir / "aviation_fleet_stock.csv"
    fleet = pd.read_csv(fleet_path)
    target_mask = (fleet["Operator"] == "Lufthansa") & (
        fleet["current_technology"] == "kerosene_medium"
    )
    target_id = str(fleet.loc[target_mask, "ID"].iloc[0])
    fleet.loc[target_mask, "Age (Years)"] = age_years
    fleet.loc[fleet["Operator"] == "Lufthansa", "investment_logic"] = "legacy_weighted_utility"
    fleet.to_csv(fleet_path, index=False)
    return fleet_path, target_id


def _cripple_alternative_technologies(case_dir: Path, *, keep: str) -> None:
    """Make every technology except `keep` catastrophically expensive to invest in."""
    technology_path = case_dir / "aviation_technology_catalog.csv"
    technology_catalog = pd.read_csv(technology_path)
    other_mask = technology_catalog["technology_name"] != keep
    technology_catalog.loc[other_mask, "capex_eur"] = 1_000_000_000_000.0
    technology_catalog.to_csv(technology_path, index=False)


def test_continue_current_disabled_by_default(tmp_path: Path) -> None:
    case_dir = _clone_case_directory(tmp_path)
    _make_young_aircraft_row(case_dir)
    _cripple_alternative_technologies(case_dir, keep="kerosene_medium")

    scenario = _load_scenario(case_dir)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    row_index = agent.fleet.frame.index[
        agent.fleet.frame["current_technology"] == "kerosene_medium"
    ][0]
    aircraft = agent.fleet.frame.loc[row_index]
    logic = LegacyWeightedUtilityLogic()

    _, _, action = logic.select_technology_for_aircraft(
        agent,
        aircraft,
        model.current_year,
        initial_ets_balance=0.0,
        row_index=int(row_index),
    )

    assert action != "continue_current"


def test_continue_current_selected_when_enabled_and_superior(tmp_path: Path) -> None:
    case_dir = _clone_case_directory(tmp_path)
    _make_young_aircraft_row(case_dir)
    _cripple_alternative_technologies(case_dir, keep="kerosene_medium")

    scenario = _load_scenario(case_dir)
    scenario.investment_timing = InvestmentTimingConfig(include_continue_option=True)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    row_index = agent.fleet.frame.index[
        agent.fleet.frame["current_technology"] == "kerosene_medium"
    ][0]
    aircraft = agent.fleet.frame.loc[row_index]
    logic = LegacyWeightedUtilityLogic()

    technology_row, evaluation, action = logic.select_technology_for_aircraft(
        agent,
        aircraft,
        model.current_year,
        initial_ets_balance=0.0,
        row_index=int(row_index),
    )

    assert action == "continue_current"
    assert technology_row["technology_name"] == "kerosene_medium"

    before_investment_cost = agent.fleet.frame.loc[row_index, "investment_cost_eur"]
    before_replacement_year = agent.fleet.frame.loc[row_index, "replacement_year"]
    agent.continue_aircraft_operation(int(row_index), evaluation, model.current_year)

    assert agent.fleet.frame.loc[row_index, "action"] == "continue_current"
    assert agent.fleet.frame.loc[row_index, "investment_cost_eur"] == before_investment_cost
    assert agent.fleet.frame.loc[row_index, "replacement_year"] == before_replacement_year


def test_planned_investment_forces_replacement_regardless_of_due_date(tmp_path: Path) -> None:
    case_dir = _clone_case_directory(tmp_path)
    fleet_path, target_id = _make_young_aircraft_row(case_dir, age_years=1.0)
    fleet = pd.read_csv(fleet_path)
    target_mask = fleet["ID"].astype(str) == target_id
    planned_year = 2026
    fleet.loc[target_mask, "planned_investment_1_year"] = planned_year
    fleet.loc[target_mask, "planned_investment_1_technology_name"] = "drop_in_saf_medium"
    fleet.to_csv(fleet_path, index=False)

    scenario = _load_scenario(case_dir)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    row_index = agent.fleet.frame.index[
        agent.fleet.frame["aircraft_id"] == int(target_id)
    ][0]

    # Confirm this aircraft would not naturally be due in the planned year.
    assert agent.fleet.frame.loc[row_index, "replacement_year"] > planned_year

    logic = LegacyWeightedUtilityLogic()
    replacement_rows = logic.replacement_row_indices(agent, planned_year)
    assert int(row_index) in replacement_rows

    logic.replace_due_aircraft(agent, planned_year, replacement_rows=[int(row_index)])

    assert agent.fleet.frame.loc[row_index, "current_technology"] == "drop_in_saf_medium"
    assert agent.fleet.frame.loc[row_index, "action"] == "planned_investment"


def test_residual_value_only_changes_npv_when_horizon_is_shorter_than_lifetime() -> None:
    scenario = _load_scenario(_passenger_case_dir())
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    aircraft = agent.fleet.frame.iloc[0]
    technology_row = agent.technology_row(str(aircraft["current_technology"]))
    life_time = int(technology_row["lifetime_years"])
    year = scenario.start_year
    logic = LegacyWeightedUtilityLogic()

    # Horizon covers the full technology lifetime: residual value must not activate.
    scenario.end_year = year + life_time - 1
    scenario.investment_timing = InvestmentTimingConfig(residual_value_method="none")
    full_horizon_disabled = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)
    scenario.investment_timing = InvestmentTimingConfig(
        residual_value_method="straight_line_remaining_life",
    )
    full_horizon_enabled = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)
    assert full_horizon_enabled.net_present_value == pytest.approx(
        full_horizon_disabled.net_present_value,
    )

    # A horizon shorter than the technology lifetime must change the NPV once enabled.
    scenario.end_year = year + max(life_time // 2, 1) - 1
    scenario.investment_timing = InvestmentTimingConfig(residual_value_method="none")
    short_horizon_disabled = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)
    scenario.investment_timing = InvestmentTimingConfig(
        residual_value_method="straight_line_remaining_life",
    )
    short_horizon_enabled = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)
    assert short_horizon_enabled.net_present_value != pytest.approx(
        short_horizon_disabled.net_present_value,
    )


def test_default_scenario_still_runs_end_to_end_with_flags_off() -> None:
    """Full regression guard: opt-in flags off must reproduce today's run behavior."""
    scenario = _load_scenario(_passenger_case_dir())
    model = NATMModel(scenario, seed=42)

    model.run()

    aircraft_summary = model.to_aircraft_frame()
    assert "action" in aircraft_summary.columns
    assert set(aircraft_summary["action"].unique()) <= {"", "invest"}
