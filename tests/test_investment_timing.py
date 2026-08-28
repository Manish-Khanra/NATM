from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from navaero_transition_model.core.agent_types import (
    AviationCargoAirlineAgent,
    AviationPassengerAirlineAgent,
    MaritimeCargoShiplineAgent,
    MaritimePassengerShiplineAgent,
)
from navaero_transition_model.core.decision_logic.legacy_weighted_utility import (
    LegacyWeightedUtilityCargoLogic,
    LegacyWeightedUtilityLogic,
    LegacyWeightedUtilityMaritimeCargoLogic,
    LegacyWeightedUtilityMaritimePassengerLogic,
)
from navaero_transition_model.core.fleet_management import Fleet, planned_investments_from_fleet
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import InvestmentTimingConfig, NATMScenario

PASSENGER_CASE_NAME = "baseline-passenger-transition"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _passenger_case_dir() -> Path:
    return _repo_root() / "data" / "input" / PASSENGER_CASE_NAME


def _clone_case_directory(tmp_path: Path) -> Path:
    source_dir = _passenger_case_dir()
    case_dir = tmp_path / PASSENGER_CASE_NAME
    shutil.copytree(source_dir, case_dir)
    return case_dir


def _load_scenario(case_dir: Path) -> NATMScenario:
    return NATMScenario.from_yaml(case_dir / "scenario.yaml")


def _append_scenario_row(
    case_dir: Path,
    *,
    variable_name: str,
    value: float,
    segment: str = "",
    technology_name: str = "",
    variable_group: str = "cost_index",
    unit: str = "value",
) -> None:
    """Append one wide-format scenario row, holding `value` constant across every year."""
    scenario_path = case_dir / "aviation_scenario.csv"
    scenario = pd.read_csv(scenario_path)
    year_columns = [column for column in scenario.columns if column.isdigit()]
    row = dict.fromkeys(scenario.columns, "")
    row.update(
        {
            "variable_group": variable_group,
            "variable_name": variable_name,
            "segment": segment,
            "technology_name": technology_name,
            "unit": unit,
        },
    )
    for year_column in year_columns:
        row[year_column] = value
    scenario = pd.concat([scenario, pd.DataFrame([row])], ignore_index=True)
    scenario.to_csv(scenario_path, index=False)


def test_investment_timing_defaults_preserve_todays_behavior() -> None:
    scenario = _load_scenario(_passenger_case_dir())

    assert scenario.investment_timing.include_continue_option is False
    assert scenario.investment_timing.residual_value_method == "none"
    assert scenario.investment_timing.minimum_holding_period == 0
    assert scenario.investment_timing.include_life_extension is False
    assert scenario.investment_timing.include_shutdown is False
    assert scenario.investment_timing.cashflow_mode == "component_based"


def test_investment_timing_config_rejects_unknown_residual_value_method() -> None:
    with pytest.raises(ValueError, match="residual_value_method"):
        InvestmentTimingConfig(residual_value_method="made_up_method")


def test_investment_timing_config_rejects_unknown_cashflow_mode() -> None:
    with pytest.raises(ValueError, match="cashflow_mode"):
        InvestmentTimingConfig(cashflow_mode="made_up_mode")


def test_investment_timing_config_requires_parameter_for_direct_cashflow_mode() -> None:
    with pytest.raises(ValueError, match="direct_net_operating_cost_parameter"):
        InvestmentTimingConfig(cashflow_mode="direct_net_operating_cost")


def test_investment_timing_config_rejects_negative_minimum_holding_period() -> None:
    with pytest.raises(ValueError, match="minimum_holding_period"):
        InvestmentTimingConfig(minimum_holding_period=-1)


def test_investment_timing_config_include_life_extension_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="include_life_extension"):
        InvestmentTimingConfig(include_life_extension=True)


def test_investment_timing_config_include_shutdown_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="include_shutdown"):
        InvestmentTimingConfig(include_shutdown=True)


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


def test_minimum_holding_period_blocks_early_replacement_until_elapsed(tmp_path: Path) -> None:
    case_dir = _clone_case_directory(tmp_path)
    fleet_path, target_id = _make_young_aircraft_row(case_dir, age_years=1.0)

    scenario = _load_scenario(case_dir)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    row_index = int(
        agent.fleet.frame.index[agent.fleet.frame["aircraft_id"] == int(target_id)][0],
    )
    technology_row = agent.technology_row("kerosene_medium")
    logic = LegacyWeightedUtilityLogic()
    evaluation = logic.calc_payback_year(
        agent,
        agent.fleet.frame.loc[row_index],
        technology_row,
        model.current_year,
        0.0,
    )
    invested_year = model.current_year
    agent.fleet.apply_technology(row_index, technology_row, evaluation, year=invested_year)
    assert agent.fleet.frame.loc[row_index, "investment_year"] == invested_year

    # A wide acceleration window alone would flag this row as an early-replacement
    # candidate long before it is genuinely due (it's conventional, so eligible).
    accelerated_year = invested_year + 2
    without_holding_period = agent.fleet.due_replacement_indices(
        accelerated_year,
        acceleration_window=50,
    )
    assert row_index in without_holding_period

    with_holding_period_active = agent.fleet.due_replacement_indices(
        accelerated_year,
        acceleration_window=50,
        minimum_holding_period=5,
    )
    assert row_index not in with_holding_period_active

    with_holding_period_elapsed = agent.fleet.due_replacement_indices(
        invested_year + 5,
        acceleration_window=50,
        minimum_holding_period=5,
    )
    assert row_index in with_holding_period_elapsed


def test_capex_multiplier_scales_asset_price_via_technology_specific_scenario_value(
    tmp_path: Path,
) -> None:
    baseline_scenario = _load_scenario(_passenger_case_dir())
    baseline_model = NATMModel(baseline_scenario, seed=42)
    baseline_agent = next(
        candidate
        for candidate in baseline_model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    baseline_aircraft = baseline_agent.fleet.frame.iloc[0]
    technology_row = baseline_agent.technology_row(str(baseline_aircraft["current_technology"]))
    year = baseline_scenario.start_year
    logic = LegacyWeightedUtilityLogic()
    baseline_evaluation = logic.calc_payback_year(
        baseline_agent,
        baseline_aircraft,
        technology_row,
        year,
        0.0,
    )

    case_dir = _clone_case_directory(tmp_path)
    _append_scenario_row(
        case_dir,
        variable_name="capex_multiplier",
        value=2.0,
        segment="medium",
        technology_name="kerosene_medium",
    )
    scenario = _load_scenario(case_dir)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    aircraft = agent.fleet.frame.iloc[0]
    scaled_evaluation = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)

    # A doubled capex_multiplier only worsens NPV through a costlier fresh investment;
    # NPV is bounded above by "no capex at all", so a strictly lower value here is
    # only possible if the multiplier reached calc_payback_year's asset_price.
    assert scaled_evaluation.net_present_value < baseline_evaluation.net_present_value


def test_direct_net_operating_cost_mode_requires_configured_parameter() -> None:
    scenario = _load_scenario(_passenger_case_dir())
    scenario.investment_timing = InvestmentTimingConfig(
        cashflow_mode="direct_net_operating_cost",
        direct_net_operating_cost_parameter="missing_direct_cost_parameter",
    )
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    aircraft = agent.fleet.frame.iloc[0]
    technology_row = agent.technology_row(str(aircraft["current_technology"]))
    logic = LegacyWeightedUtilityLogic()

    with pytest.raises(ValueError, match="missing_direct_cost_parameter"):
        logic.calc_payback_year(agent, aircraft, technology_row, scenario.start_year, 0.0)


def test_direct_net_operating_cost_mode_uses_scenario_parameter_and_keeps_depreciation(
    tmp_path: Path,
) -> None:
    case_dir = _clone_case_directory(tmp_path)
    net_operating_cost_value = 5_000_000.0
    _append_scenario_row(case_dir, variable_name="direct_ops_cost", value=net_operating_cost_value)

    scenario = _load_scenario(case_dir)
    scenario.investment_timing = InvestmentTimingConfig(
        cashflow_mode="direct_net_operating_cost",
        direct_net_operating_cost_parameter="direct_ops_cost",
    )
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    aircraft = agent.fleet.frame.iloc[0]
    technology_row = agent.technology_row(str(aircraft["current_technology"]))
    year = scenario.start_year
    logic = LegacyWeightedUtilityLogic()

    evaluation = logic.calc_payback_year(agent, aircraft, technology_row, year, 0.0)

    asset_price = float(technology_row["capex_eur"])
    depreciation_cost = float(technology_row["depreciation_cost_share"]) * asset_price
    # No direct_revenue_parameter configured: revenue defaults to 0 (matching AURIS),
    # and NATM's own depreciation charge still stays layered on top of the direct
    # parameter every period, per the "keep depreciation" behavior chosen for this mode.
    assert evaluation.effective_alternative_cost == pytest.approx(net_operating_cost_value)
    assert evaluation.effective_conventional_cost == pytest.approx(
        net_operating_cost_value + depreciation_cost,
    )


def test_direct_net_operating_cost_mode_with_revenue_parameter(tmp_path: Path) -> None:
    case_dir = _clone_case_directory(tmp_path)
    _make_young_aircraft_row(case_dir)
    net_operating_cost_value = 5_000_000.0
    revenue_value = 6_000_000.0
    _append_scenario_row(case_dir, variable_name="direct_ops_cost", value=net_operating_cost_value)
    _append_scenario_row(case_dir, variable_name="direct_ops_revenue", value=revenue_value)

    scenario = _load_scenario(case_dir)
    scenario.investment_timing = InvestmentTimingConfig(
        cashflow_mode="direct_net_operating_cost",
        direct_net_operating_cost_parameter="direct_ops_cost",
        direct_revenue_parameter="direct_ops_revenue",
    )
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[AviationPassengerAirlineAgent]
        if candidate.operator_name == "Lufthansa"
    )
    aircraft = agent.fleet.frame.loc[
        agent.fleet.frame["current_technology"] == "kerosene_medium"
    ].iloc[0]
    year = scenario.start_year
    logic = LegacyWeightedUtilityLogic()

    # evaluate_continue_current has zero capex, so unlike calc_payback_year it never
    # adds a depreciation charge in either cashflow mode: cost is the direct
    # parameter alone.
    continue_evaluation = logic.evaluate_continue_current(agent, aircraft, year, 0.0)
    assert continue_evaluation.effective_alternative_cost == pytest.approx(
        net_operating_cost_value,
    )
    assert continue_evaluation.net_present_value > 0


def test_default_scenario_still_runs_end_to_end_with_flags_off() -> None:
    """Full regression guard: opt-in flags off must reproduce today's run behavior."""
    scenario = _load_scenario(_passenger_case_dir())
    model = NATMModel(scenario, seed=42)

    model.run()

    aircraft_summary = model.to_aircraft_frame()
    assert "action" in aircraft_summary.columns
    assert set(aircraft_summary["action"].unique()) <= {"", "invest"}


# --- Cross-sector rollout: continue_current / planned investment now apply to every
# sector via the shared NATMDecisionScorer, not just aviation passenger. These cases
# prove the rollout, they don't re-derive the full aviation-passenger coverage above. ---

_ROLLOUT_CASES = [
    pytest.param(
        "baseline-cargo-transition",
        "aviation_fleet_stock.csv",
        "aviation_technology_catalog.csv",
        "Lufthansa Cargo",
        "kerosene_freight_long",
        AviationCargoAirlineAgent,
        LegacyWeightedUtilityCargoLogic,
        "select_technology_for_aircraft",
        id="aviation_cargo",
    ),
    pytest.param(
        "baseline-maritime-cargo-transition",
        "maritime_fleet_stock.csv",
        "maritime_technology_catalog.csv",
        "Hapag-Lloyd",
        "marine_diesel_deepsea",
        MaritimeCargoShiplineAgent,
        LegacyWeightedUtilityMaritimeCargoLogic,
        "select_technology_for_vessel",
        id="maritime_cargo",
    ),
    pytest.param(
        "baseline-maritime-passenger-transition",
        "maritime_fleet_stock.csv",
        "maritime_technology_catalog.csv",
        "DFDS",
        "marine_diesel_regional_passenger",
        MaritimePassengerShiplineAgent,
        LegacyWeightedUtilityMaritimePassengerLogic,
        "select_technology_for_vessel",
        id="maritime_passenger",
    ),
]


# The generic capex-crippling technique below relies on reinvesting-in-the-same-
# technology scoring strictly worse than continuing. Maritime passenger's payback-year
# fallback (see LegacyWeightedUtilityMaritimePassengerLogic._payback_year_fallback)
# instead saturates economic_utility to 1.0 whenever payback never occurs, which ties
# reinvestment with continuing regardless of capex. It's covered separately below by
# test_continue_current_selected_for_maritime_passenger, using a setup suited to that
# sector's ranking behavior instead.
_CONTINUE_CURRENT_CASES = [case for case in _ROLLOUT_CASES if case.id != "maritime_passenger"]


@pytest.mark.parametrize(
    (
        "case_name",
        "fleet_filename",
        "technology_filename",
        "operator_name",
        "current_technology",
        "agent_class",
        "logic_class",
        "select_method",
    ),
    _CONTINUE_CURRENT_CASES,
)
def test_continue_current_rolled_out_to_other_sectors(
    tmp_path: Path,
    case_name: str,
    fleet_filename: str,
    technology_filename: str,
    operator_name: str,
    current_technology: str,
    agent_class: type,
    logic_class: type,
    select_method: str,
) -> None:
    source_dir = _repo_root() / "data" / "input" / case_name
    case_dir = tmp_path / case_name
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / fleet_filename
    fleet = pd.read_csv(fleet_path)
    target_mask = (fleet["Operator"] == operator_name) & (
        fleet["current_technology"] == current_technology
    )
    fleet.loc[target_mask, "Age (Years)"] = 1.0
    fleet.to_csv(fleet_path, index=False)

    # Cripple every technology's capex, including the currently-installed one: a
    # fresh reinvestment in the same technology can otherwise pay back just as
    # fast as continuing (economic_utility clamps to 1.0 either way), tying with
    # continue_current and winning the stable sort on iteration order alone. With
    # every investment made unaffordable, only continuing (zero capex) stays
    # attractive, so the comparison is unambiguous.
    technology_path = case_dir / technology_filename
    technology_catalog = pd.read_csv(technology_path)
    technology_catalog["capex_eur"] = 1_000_000_000_000.0
    technology_catalog.to_csv(technology_path, index=False)

    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    scenario.investment_timing = InvestmentTimingConfig(include_continue_option=True)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[agent_class]
        if candidate.operator_name == operator_name
    )
    row_index = agent.fleet.frame.index[
        agent.fleet.frame["current_technology"] == current_technology
    ][0]
    asset = agent.fleet.frame.loc[row_index]
    logic = logic_class()

    technology_row, _evaluation, action = getattr(logic, select_method)(
        agent,
        asset,
        model.current_year,
        initial_ets_balance=0.0,
        row_index=int(row_index),
    )

    assert action == "continue_current"
    assert technology_row["technology_name"] == current_technology


@pytest.mark.parametrize(
    (
        "case_name",
        "fleet_filename",
        "technology_filename",
        "operator_name",
        "current_technology",
        "agent_class",
        "logic_class",
        "select_method",
    ),
    _ROLLOUT_CASES,
)
def test_planned_investment_rolled_out_to_other_sectors(
    tmp_path: Path,
    case_name: str,
    fleet_filename: str,
    technology_filename: str,
    operator_name: str,
    current_technology: str,
    agent_class: type,
    logic_class: type,
    select_method: str,
) -> None:
    del technology_filename, select_method
    source_dir = _repo_root() / "data" / "input" / case_name
    case_dir = tmp_path / case_name
    shutil.copytree(source_dir, case_dir)

    fleet_path = case_dir / fleet_filename
    fleet = pd.read_csv(fleet_path)
    target_mask = (fleet["Operator"] == operator_name) & (
        fleet["current_technology"] == current_technology
    )
    fleet.loc[target_mask, "Age (Years)"] = 1.0
    target_id = str(fleet.loc[target_mask, "ID"].iloc[0])
    planned_year = 2026
    fleet.loc[target_mask, "planned_investment_1_year"] = planned_year
    fleet.loc[target_mask, "planned_investment_1_technology_name"] = current_technology
    fleet.to_csv(fleet_path, index=False)

    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[agent_class]
        if candidate.operator_name == operator_name
    )
    row_index = agent.fleet.frame.index[agent.fleet.frame["aircraft_id"] == int(target_id)][0]

    logic = logic_class()
    replacement_rows = logic.replacement_row_indices(agent, planned_year)
    assert int(row_index) in replacement_rows


def test_continue_current_selected_for_maritime_passenger(tmp_path: Path) -> None:
    """Maritime passenger's own continue_current proof.

    Its payback-year fallback (`_payback_year_fallback` returning `max_npv_year`)
    saturates economic_utility to 1.0 for any reinvestment that never pays back
    within its lifetime, so reinvesting in the current technology always ties
    continue_current on total_utility regardless of capex, as documented on
    `_CONTINUE_CURRENT_CASES` above. This test instead disqualifies the current
    technology from fresh investment via `service_entry_year`, matching how a
    real phased-out technology would behave: still fine to keep operating, no
    longer purchasable new. The one remaining alternative (biofuel) scores lower
    on total_utility than continuing, so continue_current wins unambiguously.
    """
    case_name = "baseline-maritime-passenger-transition"
    source_dir = _repo_root() / "data" / "input" / case_name
    case_dir = tmp_path / case_name
    shutil.copytree(source_dir, case_dir)
    operator_name = "DFDS"
    current_technology = "marine_diesel_regional_passenger"

    fleet_path = case_dir / "maritime_fleet_stock.csv"
    fleet = pd.read_csv(fleet_path)
    target_mask = (fleet["Operator"] == operator_name) & (
        fleet["current_technology"] == current_technology
    )
    fleet.loc[target_mask, "Age (Years)"] = 1.0
    fleet.to_csv(fleet_path, index=False)

    technology_path = case_dir / "maritime_technology_catalog.csv"
    technology_catalog = pd.read_csv(technology_path)
    current_mask = technology_catalog["technology_name"] == current_technology
    technology_catalog.loc[current_mask, "service_entry_year"] = 2999
    technology_catalog.to_csv(technology_path, index=False)

    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    scenario.investment_timing = InvestmentTimingConfig(include_continue_option=True)
    model = NATMModel(scenario, seed=42)
    agent = next(
        candidate
        for candidate in model.agents_by_type[MaritimePassengerShiplineAgent]
        if candidate.operator_name == operator_name
    )
    row_index = agent.fleet.frame.index[
        agent.fleet.frame["current_technology"] == current_technology
    ][0]
    asset = agent.fleet.frame.loc[row_index]
    logic = LegacyWeightedUtilityMaritimePassengerLogic()

    technology_row, evaluation, action = logic.select_technology_for_vessel(
        agent,
        asset,
        model.current_year,
        initial_ets_balance=0.0,
        row_index=int(row_index),
    )

    assert action == "continue_current"
    assert technology_row["technology_name"] == current_technology

    before_investment_cost = agent.fleet.frame.loc[row_index, "investment_cost_eur"]
    before_replacement_year = agent.fleet.frame.loc[row_index, "replacement_year"]
    agent.continue_vessel_operation(int(row_index), evaluation, model.current_year)

    assert agent.fleet.frame.loc[row_index, "action"] == "continue_current"
    assert agent.fleet.frame.loc[row_index, "investment_cost_eur"] == before_investment_cost
    assert agent.fleet.frame.loc[row_index, "replacement_year"] == before_replacement_year
