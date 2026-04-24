import shutil
import sqlite3
from copy import deepcopy
from pathlib import Path

import mesa
import pandas as pd
import pytest
from navaero_transition_model.cli import resolve_case_config
from navaero_transition_model.core.agent_types import (
    AviationCargoAirlineAgent,
    AviationPassengerAirlineAgent,
    BaseOperatorAgent,
    MaritimeCargoShiplineAgent,
    MaritimePassengerShiplineAgent,
)
from navaero_transition_model.core.case_inputs import (
    AviationPassengerCaseData,
    MaritimePassengerCaseData,
    ScenarioTable,
    TechnologyCatalog,
)
from navaero_transition_model.core.database import SQLiteSimulationStore
from navaero_transition_model.core.loaders import (
    load_aviation_passenger_case,
    load_maritime_passenger_case,
)
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.scenario import NATMScenario


def load_default_scenario() -> NATMScenario:
    scenario_path = Path(__file__).resolve().parents[1] / resolve_case_config("baseline-transition")
    return NATMScenario.from_yaml(scenario_path)


def load_cargo_scenario() -> NATMScenario:
    scenario_path = Path(__file__).resolve().parents[1] / resolve_case_config(
        "baseline-cargo-transition",
    )
    return NATMScenario.from_yaml(scenario_path)


def load_maritime_cargo_scenario() -> NATMScenario:
    scenario_path = Path(__file__).resolve().parents[1] / resolve_case_config(
        "baseline-maritime-cargo-transition",
    )
    return NATMScenario.from_yaml(scenario_path)


def load_maritime_passenger_scenario() -> NATMScenario:
    scenario_path = Path(__file__).resolve().parents[1] / resolve_case_config(
        "baseline-maritime-passenger-transition",
    )
    return NATMScenario.from_yaml(scenario_path)


def _set_scenario_value(
    scenario_table: ScenarioTable,
    variable_name: str,
    year: int,
    value: float,
    **scope: str,
) -> None:
    long_frame = scenario_table._long.copy()
    mask = (long_frame["variable_name"] == variable_name) & (long_frame["year"] == year)
    for column, scope_value in scope.items():
        requested = str(scope_value).strip()
        mask &= long_frame[column].fillna("").astype(str).str.strip().eq(requested)

    if mask.any():
        long_frame.loc[mask, "value"] = float(value)
    else:
        row = {column: "" for column in long_frame.columns}
        row["variable_group"] = "test"
        row["variable_name"] = variable_name
        row["year"] = int(year)
        row["value"] = float(value)
        row["unit"] = ""
        for column, scope_value in scope.items():
            row[column] = str(scope_value).strip()
        long_frame = pd.concat([long_frame, pd.DataFrame([row])], ignore_index=True)

    scenario_table._long = long_frame.reset_index(drop=True)
    scenario_table._cache.clear()


def _set_capacity_matched_demand(model: NATMModel, year: int) -> None:
    scenario_table = model.aviation_passenger_inputs.scenario_table
    country_segment_totals: dict[tuple[str, str], float] = {}
    operator_segment_capacities: dict[tuple[str, str, str], float] = {}

    for agent in model.agents_by_type[AviationPassengerAirlineAgent]:
        segments = sorted(agent.fleet.frame["segment"].dropna().unique())
        for segment in segments:
            capacity = agent.segment_passenger_km_capacity(str(segment), year)
            operator_segment_capacities[
                (agent.operator_country, agent.operator_name, str(segment))
            ] = capacity
            key = (agent.operator_country, str(segment))
            country_segment_totals[key] = country_segment_totals.get(key, 0.0) + capacity

    for (country, segment), total_capacity in country_segment_totals.items():
        _set_scenario_value(
            scenario_table,
            "passenger_km_demand",
            year,
            total_capacity,
            country=country,
            segment=segment,
        )

    for (country, operator_name, segment), operator_capacity in operator_segment_capacities.items():
        total_capacity = country_segment_totals[(country, segment)]
        market_share = 0.0 if total_capacity <= 0.0 else operator_capacity / total_capacity
        _set_scenario_value(
            scenario_table,
            "operator_market_share",
            year,
            market_share,
            country=country,
            operator_name=operator_name,
            segment=segment,
        )

    long_frame = scenario_table._long.copy()
    delivery_mask = (long_frame["variable_name"] == "planned_delivery_count") & (
        long_frame["year"] == year
    )
    long_frame.loc[delivery_mask, "value"] = 0.0
    scenario_table._long = long_frame.reset_index(drop=True)
    scenario_table._cache.clear()


def _clone_case_directory(tmp_path: Path) -> Path:
    source_dir = Path(__file__).resolve().parents[1] / "data" / "baseline-transition"
    case_dir = tmp_path / "baseline-transition"
    case_dir.mkdir()
    for source_path in source_dir.iterdir():
        if source_path.is_file():
            shutil.copy2(source_path, case_dir / source_path.name)
    return case_dir


def test_default_scenario_runs_end_to_end() -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)

    history = model.run()
    summary = model.to_frame()
    agent_summary = model.to_agent_frame()
    aircraft_summary = model.to_aircraft_frame()
    technology_summary = model.to_aviation_technology_frame()
    energy_emissions_summary = model.to_aviation_energy_emissions_frame()
    investment_summary = model.to_aviation_investment_frame()
    aviation_path = scenario.operator_input_path("aviation")
    maritime_path = scenario.operator_input_path("maritime")
    countries_path = scenario.environment_input_path("countries")
    corridors_path = scenario.environment_input_path("corridors")

    assert isinstance(model, mesa.Model)
    assert scenario.enabled_sectors == ("aviation",)
    assert scenario.applications_for_sector("aviation") == ("passenger",)
    assert len(history) == scenario.steps
    assert aviation_path is None
    assert maritime_path is None
    assert countries_path is not None and countries_path.exists()
    assert corridors_path is not None and corridors_path.exists()
    assert len(model.agents) == 4
    assert all(isinstance(agent, mesa.Agent) for agent in model.agents)
    assert all(isinstance(agent, BaseOperatorAgent) for agent in model.agents)
    assert all(isinstance(agent, AviationPassengerAirlineAgent) for agent in model.agents)
    assert len(model.agents_by_type[AviationPassengerAirlineAgent]) == 4
    assert len(model.get_sector_agents("maritime")) == 0
    assert history[0].aviation_alternative_share < history[-1].aviation_alternative_share
    assert all(snapshot.maritime_alternative_share == 0.0 for snapshot in history)
    assert summary["carbon_price"].iloc[0] < summary["carbon_price"].iloc[-1]
    assert "environment_aviation_infrastructure" in summary.columns
    assert "environment_maritime_infrastructure" in summary.columns
    assert "aviation_transition_pressure" in summary.columns
    assert "maritime_transition_pressure" in summary.columns
    assert {"aviation"} == set(agent_summary["sector_name"].unique())
    assert agent_summary["operator_name"].nunique() == len(model.agents)
    assert "operator_country" in agent_summary.columns
    assert {"legacy_weighted_utility"} == set(agent_summary["investment_logic"].unique())
    assert not aircraft_summary.empty
    assert not technology_summary.empty
    assert not energy_emissions_summary.empty
    assert not investment_summary.empty
    assert "main_hub" in aircraft_summary.columns
    assert "current_technology" in aircraft_summary.columns
    assert "chargeable_emission" in aircraft_summary.columns
    assert "remaining_ets_allocation" in aircraft_summary.columns
    assert "aircraft_count" in technology_summary.columns
    assert "total_emission" in energy_emissions_summary.columns
    assert "chargeable_emission" in energy_emissions_summary.columns
    assert "operator_name" in energy_emissions_summary.columns
    assert "primary_energy_carrier" in energy_emissions_summary.columns
    assert "secondary_energy_carrier" in energy_emissions_summary.columns
    assert "investment_cost_eur" in investment_summary.columns
    assert energy_emissions_summary["primary_energy_consumption"].sum() > 0.0
    assert energy_emissions_summary["total_emission"].sum() > 0.0
    assert (energy_emissions_summary["chargeable_emission"] >= 0.0).all()
    assert "Germany" in model.environment.countries
    germany_signal = model.environment.signal_for("Germany", "aviation")
    assert 0.0 <= germany_signal.infrastructure_readiness <= 1.0
    assert 0.0 <= germany_signal.corridor_exposure <= 1.0
    assert model.aviation_passenger_inputs is not None
    assert isinstance(list(model.agents)[0], AviationPassengerAirlineAgent)


def test_aviation_fleet_stock_is_aggregated_by_operator() -> None:
    case_dir = Path(__file__).resolve().parents[1] / "data" / "baseline-transition"
    profiles = load_aviation_passenger_case(case_dir).grouped_operator_fleet()
    grouped = {
        (operator_name, operator_country): fleet_df
        for (operator_name, operator_country), fleet_df in profiles
    }

    assert {operator_name for operator_name, _ in grouped} == {
        "Lufthansa",
        "Eurowings",
        "Air France",
        "Ryanair",
    }
    assert ("Lufthansa", "Germany") in grouped
    assert ("Air France", "France") in grouped
    assert ("Ryanair", "Ireland") in grouped
    assert set(grouped[("Lufthansa", "Germany")]["main_hub"].unique()) == {"Frankfurt"}


def test_stronger_policy_accelerates_adoption() -> None:
    baseline = load_default_scenario()
    stronger_policy = deepcopy(baseline)
    baseline_model = NATMModel(baseline, seed=42)
    stronger_model = NATMModel(stronger_policy, seed=42)

    stronger_table = stronger_model.aviation_passenger_inputs.scenario_table
    stronger_long = stronger_table._long.copy()
    stronger_long.loc[
        stronger_long["variable_name"] == "carbon_price",
        "value",
    ] = stronger_long.loc[stronger_long["variable_name"] == "carbon_price", "value"] * 1.35
    stronger_long.loc[
        stronger_long["variable_name"] == "clean_fuel_subsidy",
        "value",
    ] = (
        pd.to_numeric(
            stronger_long.loc[stronger_long["variable_name"] == "clean_fuel_subsidy", "value"],
            errors="coerce",
        )
        + 0.08
    )
    stronger_long.loc[
        stronger_long["variable_name"] == "adoption_mandate",
        "value",
    ] = (
        pd.to_numeric(
            stronger_long.loc[stronger_long["variable_name"] == "adoption_mandate", "value"],
            errors="coerce",
        )
        + 0.10
    )
    stronger_table._long = stronger_long
    stronger_table._cache.clear()

    baseline_final = baseline_model.run()[-1]
    stronger_final = stronger_model.run()[-1]

    assert stronger_final.aviation_alternative_share > baseline_final.aviation_alternative_share
    assert stronger_final.maritime_alternative_share == baseline_final.maritime_alternative_share


def test_aviation_passenger_case_loader_reads_three_file_structure() -> None:
    case_dir = Path(__file__).resolve().parents[1] / "data" / "baseline-transition"
    case_inputs = load_aviation_passenger_case(case_dir)

    assert isinstance(case_inputs, AviationPassengerCaseData)
    assert not case_inputs.fleet.empty
    assert isinstance(case_inputs.technology_catalog, TechnologyCatalog)
    assert not case_inputs.technology_catalog.to_frame().empty
    assert isinstance(case_inputs.scenario_table, ScenarioTable)
    assert not case_inputs.scenario_wide.empty
    assert not case_inputs.scenario_long.empty
    assert "operator_key" in case_inputs.fleet.columns
    assert "main_hub" in case_inputs.fleet.columns
    assert {"short", "medium", "long"} <= set(case_inputs.fleet["segment"].unique())
    assert "technology_name" in case_inputs.technology_catalog.to_frame().columns
    assert "service_entry_year" in case_inputs.technology_catalog.to_frame().columns
    assert {"legacy_weighted_utility"} == set(case_inputs.fleet["investment_logic"].unique())
    assert case_inputs.scenario_long["year"].min() == 2025
    assert case_inputs.scenario_long["year"].max() == 2035
    assert "primary_energy_price" in set(case_inputs.scenario_long["variable_name"])
    assert "technology_availability" in set(case_inputs.scenario_long["variable_name"])
    assert "saf_availability" in set(case_inputs.scenario_long["variable_name"])
    assert "maximum_secondary_energy_share" in set(case_inputs.scenario_long["variable_name"])
    assert "passenger_km_demand" in set(case_inputs.scenario_long["variable_name"])
    assert "operator_market_share" in set(case_inputs.scenario_long["variable_name"])


def test_technology_catalog_lookup_is_name_based_with_optional_segment_metadata() -> None:
    case_dir = Path(__file__).resolve().parents[1] / "data" / "baseline-transition"
    catalog = TechnologyCatalog.from_csv(case_dir / "aviation_technology_catalog.csv")

    row = catalog.row_for("kerosene_medium", segment="short")
    assert row["technology_name"] == "kerosene_medium"

    candidates = catalog.candidates_for_operation(
        segment="long",
        minimum_trip_length_km=9000.0,
    )
    assert not candidates.empty
    assert (pd.to_numeric(candidates["trip_length_km"], errors="coerce") >= 9000.0).all()
    assert (
        candidates["segment"].fillna("").astype(str).str.strip().str.lower().isin(["", "long"])
    ).all()


def test_maritime_passenger_scenario_runs_end_to_end() -> None:
    scenario = load_maritime_passenger_scenario()
    model = NATMModel(scenario, seed=42)

    history = model.run()
    agent_summary = model.to_agent_frame()
    aircraft_summary = model.to_aircraft_frame()
    technology_summary = model.to_maritime_technology_frame()
    energy_emissions_summary = model.to_maritime_energy_emissions_frame()
    investment_summary = model.to_maritime_investment_frame()

    assert scenario.enabled_sectors == ("maritime",)
    assert scenario.applications_for_sector("maritime") == ("passenger",)
    assert len(history) == scenario.steps
    assert len(model.agents) == 2
    assert all(isinstance(agent, BaseOperatorAgent) for agent in model.agents)
    assert all(isinstance(agent, MaritimePassengerShiplineAgent) for agent in model.agents)
    assert len(model.agents_by_type[MaritimePassengerShiplineAgent]) == 2
    assert len(model.get_sector_agents("aviation")) == 0
    assert {"maritime"} == set(agent_summary["sector_name"].unique())
    assert {"passenger"} == set(agent_summary["application_name"].unique())
    assert {"legacy_weighted_utility_maritime_passenger"} == set(
        agent_summary["investment_logic"].unique(),
    )
    assert not aircraft_summary.empty
    assert not technology_summary.empty
    assert not energy_emissions_summary.empty
    assert not investment_summary.empty
    assert {"passenger"} == set(technology_summary["application_name"].unique())
    assert "chargeable_emission" in energy_emissions_summary.columns
    assert energy_emissions_summary["primary_energy_consumption"].sum() > 0.0
    assert energy_emissions_summary["total_emission"].sum() > 0.0
    assert history[0].maritime_alternative_share <= history[-1].maritime_alternative_share


def test_maritime_passenger_case_loader_reads_three_file_structure() -> None:
    case_dir = (
        Path(__file__).resolve().parents[1] / "data" / "baseline-maritime-passenger-transition"
    )
    case_inputs = load_maritime_passenger_case(case_dir)

    assert isinstance(case_inputs, MaritimePassengerCaseData)
    assert not case_inputs.fleet.empty
    assert isinstance(case_inputs.technology_catalog, TechnologyCatalog)
    assert isinstance(case_inputs.scenario_table, ScenarioTable)
    assert "main_hub" in case_inputs.fleet.columns
    assert {"regional", "overnight"} <= set(case_inputs.fleet["segment"].unique())
    assert "passenger_km_demand" in set(case_inputs.scenario_long["variable_name"])
    assert "operator_market_share" in set(case_inputs.scenario_long["variable_name"])
    assert "passenger_economy_class_occupancy" in set(case_inputs.scenario_long["variable_name"])
    assert "passenger_economy_class" in case_inputs.technology_catalog.to_frame().columns


@pytest.mark.parametrize(
    ("missing_variable", "message_fragment"),
    [
        ("passenger_km_demand", "passenger_km_demand"),
        ("operator_market_share", "operator_market_share"),
    ],
)
def test_missing_capacity_planning_inputs_fail_clearly(
    tmp_path: Path,
    missing_variable: str,
    message_fragment: str,
) -> None:
    case_dir = _clone_case_directory(tmp_path)
    scenario_csv = case_dir / "aviation_scenario.csv"
    scenario_frame = pd.read_csv(scenario_csv)
    scenario_frame = scenario_frame.loc[scenario_frame["variable_name"] != missing_variable].copy()
    scenario_frame.to_csv(scenario_csv, index=False)

    scenario = NATMScenario.from_yaml(case_dir / "scenario.yaml")
    with pytest.raises(ValueError, match=message_fragment):
        NATMModel(scenario, seed=42)


def test_constant_demand_without_planned_deliveries_adds_no_growth_aircraft() -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)
    planning_year = model.current_year + 1
    _set_capacity_matched_demand(model, planning_year)
    before_counts = {
        agent.operator_name: len(agent.fleet.frame)
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
    }

    model.step()

    after_counts = {
        agent.operator_name: len(agent.fleet.frame)
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
    }
    assert after_counts == before_counts


def test_higher_market_share_gets_more_growth_aircraft() -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)
    planning_year = model.current_year + 1
    _set_capacity_matched_demand(model, planning_year)

    lufthansa = next(
        agent
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
        if agent.operator_name == "Lufthansa"
    )
    eurowings = next(
        agent
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
        if agent.operator_name == "Eurowings"
    )
    scenario_table = model.aviation_passenger_inputs.scenario_table

    _set_scenario_value(
        scenario_table,
        "operator_market_share",
        planning_year,
        0.80,
        country="Germany",
        operator_name="Lufthansa",
        segment="medium",
    )
    _set_scenario_value(
        scenario_table,
        "operator_market_share",
        planning_year,
        0.20,
        country="Germany",
        operator_name="Eurowings",
        segment="medium",
    )
    _set_scenario_value(
        scenario_table,
        "passenger_km_demand",
        planning_year,
        3_000_000_000.0,
        country="Germany",
        segment="medium",
    )

    before_lufthansa = len(lufthansa.fleet.frame)
    before_eurowings = len(eurowings.fleet.frame)

    model.step()

    assert (
        len(lufthansa.fleet.frame) - before_lufthansa
        > len(eurowings.fleet.frame) - before_eurowings
    )


def test_planned_deliveries_cover_gap_before_endogenous_growth() -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)
    planning_year = model.current_year + 1
    _set_capacity_matched_demand(model, planning_year)

    lufthansa = next(
        agent
        for agent in model.agents_by_type[AviationPassengerAirlineAgent]
        if agent.operator_name == "Lufthansa"
    )
    scenario_table = model.aviation_passenger_inputs.scenario_table
    template = lufthansa.segment_template("medium")
    planned_technology = lufthansa.technology_row("drop_in_saf_medium", "medium")
    planned_capacity = lufthansa.aircraft_passenger_km_capacity(
        template,
        planned_technology,
        planning_year,
    )
    lufthansa_capacity = lufthansa.segment_passenger_km_capacity("medium", planning_year)

    _set_scenario_value(
        scenario_table,
        "operator_market_share",
        planning_year,
        1.0,
        country="Germany",
        operator_name="Lufthansa",
        segment="medium",
    )
    _set_scenario_value(
        scenario_table,
        "operator_market_share",
        planning_year,
        0.0,
        country="Germany",
        operator_name="Eurowings",
        segment="medium",
    )
    _set_scenario_value(
        scenario_table,
        "passenger_km_demand",
        planning_year,
        lufthansa_capacity + (0.80 * planned_capacity),
        country="Germany",
        segment="medium",
    )
    _set_scenario_value(
        scenario_table,
        "planned_delivery_count",
        planning_year,
        1.0,
        country="Germany",
        operator_name="Lufthansa",
        segment="medium",
        technology_name="drop_in_saf_medium",
    )

    before_count = len(lufthansa.fleet.frame)
    model.step()

    added_count = len(lufthansa.fleet.frame) - before_count
    planned_investments = lufthansa.fleet.frame.loc[
        (pd.to_numeric(lufthansa.fleet.frame["investment_year"], errors="coerce") == planning_year)
        & lufthansa.fleet.frame["current_technology"].eq("drop_in_saf_medium")
    ]
    assert added_count == 1
    assert not planned_investments.empty


def test_sqlite_store_writes_inputs_and_outputs(tmp_path: Path) -> None:
    scenario = load_default_scenario()
    model = NATMModel(scenario, seed=42)
    model.run()

    database_path = tmp_path / "natm_run.sqlite"
    run_id = SQLiteSimulationStore(database_path).write_run(model, scenario)

    assert database_path.exists()
    assert run_id

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).fetchall()
        }
        assert "runs" in tables
        assert "input_aviation_fleet" in tables
        assert "input_aviation_technology_catalog" in tables
        assert "input_aviation_scenario" in tables
        assert "output_model_summary" in tables
        assert "output_aviation_energy_emissions" in tables

        run_count = connection.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        assert run_count == 1


def test_cargo_scenario_runs_end_to_end() -> None:
    scenario = load_cargo_scenario()
    model = NATMModel(scenario, seed=42)

    history = model.run()
    summary = model.to_frame()
    aircraft_summary = model.to_aircraft_frame()

    assert scenario.enabled_sectors == ("aviation",)
    assert scenario.applications_for_sector("aviation") == ("cargo",)
    assert len(history) == scenario.steps
    assert len(model.agents) == 2
    assert all(isinstance(agent, AviationCargoAirlineAgent) for agent in model.agents)
    assert "application_name" in aircraft_summary.columns
    assert set(aircraft_summary["application_name"].dropna().unique()) == {"cargo"}
    assert summary.iloc[-1]["aviation_alternative_share"] >= 0.0


def test_maritime_cargo_scenario_runs_end_to_end() -> None:
    scenario = load_maritime_cargo_scenario()
    model = NATMModel(scenario, seed=42)

    history = model.run()
    summary = model.to_frame()
    aircraft_summary = model.to_aircraft_frame()
    technology_summary = model.to_maritime_technology_frame()
    energy_summary = model.to_maritime_energy_emissions_frame()
    investment_summary = model.to_maritime_investment_frame()

    assert scenario.enabled_sectors == ("maritime",)
    assert scenario.applications_for_sector("maritime") == ("cargo",)
    assert len(history) == scenario.steps
    assert len(model.agents) == 2
    assert all(isinstance(agent, MaritimeCargoShiplineAgent) for agent in model.agents)
    assert {"cargo"} == set(aircraft_summary["application_name"].dropna().unique())
    assert {"maritime"} == set(aircraft_summary["sector_name"].dropna().unique())
    assert "vessel_id" in aircraft_summary.columns
    assert not technology_summary.empty
    assert not energy_summary.empty
    assert not investment_summary.empty
    assert "vessel_count" in technology_summary.columns
    assert "vessel_count" in energy_summary.columns
    assert "vessel_count" in investment_summary.columns
    assert summary.iloc[-1]["maritime_alternative_share"] >= 0.0
