from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

import pandas as pd
from navaero_transition_model.aviation_preprocessing import aircraft_type_mapping
from navaero_transition_model.aviation_preprocessing.activity_profiles import (
    AviationActivityProfileBuilder,
)
from navaero_transition_model.aviation_preprocessing.aircraft_type_mapping import (
    map_to_openap_type,
)
from navaero_transition_model.aviation_preprocessing.allocation import AviationAllocationBuilder
from navaero_transition_model.aviation_preprocessing.baseline import AviationBaselineBuilder
from navaero_transition_model.aviation_preprocessing.filters import (
    filter_german_airport_departures,
    filter_german_flag_fleet,
)
from navaero_transition_model.aviation_preprocessing.flight_activity_fuel import (
    build_openap_activity_profiles,
    estimate_trip_fuel_and_emissions,
    run_openap_trip_estimation,
)
from navaero_transition_model.aviation_preprocessing.flightlists import (
    FlightlistIngestionConfig,
    OpenSkyFlightlistIngestor,
)
from navaero_transition_model.aviation_preprocessing.matching import AviationStockMatcher
from navaero_transition_model.aviation_preprocessing.mission_profile import (
    generate_synthetic_mission_profile,
)
from navaero_transition_model.aviation_preprocessing.openap_backend import (
    OpenAPFuelConfig,
    OpenAPFuelEmissionBackend,
)
from navaero_transition_model.aviation_preprocessing.opensky_aircraft_db import (
    OpenSkyAircraftDatabaseProcessor,
)
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner
from navaero_transition_model.core.case_inputs import AviationPassengerCaseData, TechnologyCatalog
from navaero_transition_model.core.fleet_management import Fleet
from navaero_transition_model.core.scenario import NATMScenario


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _passenger_case_dir() -> Path:
    return _repo_root() / "data" / "baseline-passenger-transition"


def test_scenario_loads_optional_aviation_preprocessing_config() -> None:
    scenario = NATMScenario.from_yaml(
        _passenger_case_dir() / "scenario.yaml",
    )
    config = scenario.aviation_preprocessing_config()

    assert config is not None
    assert config.enabled is True
    assert config.stock_input == "aviation_fleet_stock.csv"
    assert config.openap.estimate_fuel is True
    assert config.openap.mode == "synthetic"
    assert config.resolve_path(scenario.base_path, "stock_input").name == (
        "aviation_fleet_stock.csv"
    )


def test_scenario_without_preprocessing_remains_valid(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(
        dedent(
            """
            name: minimal
            start_year: 2025
            end_year: 2026

            sectors:
              aviation:
                - passenger
            """
        ),
        encoding="utf-8",
    )

    scenario = NATMScenario.from_yaml(scenario_path)

    assert scenario.aviation_preprocessing_config() is None


def test_openap_aircraft_type_mapping_exact_fallback_and_unsupported(monkeypatch) -> None:
    supported_types = {"A320", "B738"}
    monkeypatch.setattr(
        aircraft_type_mapping,
        "is_openap_supported",
        lambda aircraft_type: str(aircraft_type).upper() in supported_types,
    )

    assert map_to_openap_type("A320").mapping_status == "exact"

    a20n_result = map_to_openap_type("A20N")
    assert a20n_result.openap_type == "A320"
    assert a20n_result.mapping_status == "fallback"

    unknown_result = map_to_openap_type("ZZZZ")
    assert unknown_result.openap_type is None
    assert unknown_result.mapping_status == "unsupported"


def test_openap_synthetic_mission_profile_has_positive_steps() -> None:
    profile = generate_synthetic_mission_profile(
        distance_km=500.0,
        openap_type="A320",
        config=OpenAPFuelConfig(),
    )

    assert {"climb", "cruise", "descent"}.issubset(set(profile["phase"]))
    assert (profile["delta_t_seconds"] > 0.0).all()
    assert (profile["alt_ft"] >= 0.0).all()


def test_openap_trip_fuel_estimation_returns_positive_values(monkeypatch) -> None:
    monkeypatch.setattr(
        aircraft_type_mapping,
        "is_openap_supported",
        lambda aircraft_type: str(aircraft_type).upper() == "A320",
    )
    config = OpenAPFuelConfig(include_non_co2=False)
    backend = OpenAPFuelEmissionBackend(config)
    result = estimate_trip_fuel_and_emissions(
        pd.Series(
            {
                "flight_id": "LH001",
                "icao24": "3c6701",
                "aircraft_type": "A320",
                "origin": "FRA",
                "destination": "DUB",
                "day": "2022-01-06",
                "distance_km": 1087.0,
                "range_km": 6950.0,
                "technology_mtow": 78000.0,
                "technology_oew": 41413.0,
                "technology_fuel_capacity_kwh": 850000.0,
                "technology_economy_seats": 150.0,
                "technology_business_seats": 12.0,
                "technology_first_class_seats": 0.0,
                "economy_occupancy": 0.80,
                "business_occupancy": 0.60,
                "first_occupancy": 0.0,
            }
        ),
        backend,
        config,
    )

    assert float(result["fuel_kg"]) > 0.0
    assert float(result["energy_mwh"]) > 0.0
    assert float(result["co2_kg"]) > 0.0
    assert float(result["final_mass_kg"]) < float(result["initial_mass_kg"])
    assert float(result["passenger_payload_kg"]) > 0.0
    assert float(result["estimated_block_fuel_kg"]) > 0.0
    assert result["mass_estimation_method"] == "oew_payload_block_fuel"


def test_openap_trip_outputs_and_activity_profile_aggregation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        aircraft_type_mapping,
        "is_openap_supported",
        lambda aircraft_type: str(aircraft_type).upper() in {"A319", "A320", "A359"},
    )
    repo_root = _repo_root()
    example_root = repo_root / "data" / "examples" / "aviation_preprocessing"
    raw_opensky_path = example_root / "opensky_aircraft_db_sample.csv"
    airports_path = example_root / "airports_sample.csv"
    flightlist_dir = example_root / "opensky_flightlists"

    processed_db_path = tmp_path / "opensky_aircraft_db_processed.csv"
    processed_db = OpenSkyAircraftDatabaseProcessor().process(
        raw_opensky_path,
        output_path=processed_db_path,
    )
    baseline_case_dir = _passenger_case_dir()
    cleaned_stock = AviationStockCleaner().clean(baseline_case_dir / "aviation_fleet_stock.csv")
    match_result = AviationStockMatcher().match(cleaned_stock, processed_db)
    enriched_stock_path = tmp_path / "aviation_fleet_stock_enriched.csv"
    match_result.enriched_stock.to_csv(enriched_stock_path, index=False)
    OpenSkyFlightlistIngestor(
        FlightlistIngestionConfig(
            input_folder=flightlist_dir,
            output_parquet_path=tmp_path / "opensky_flightlist_processed.parquet",
            airport_metadata_path=airports_path,
            year_start=2022,
            year_end=2022,
        ),
    ).ingest()

    outputs = run_openap_trip_estimation(
        processed_flightlist_path=tmp_path / "opensky_flightlist_processed.parquet",
        airport_metadata_path=airports_path,
        aircraft_db_processed_path=processed_db_path,
        fleet_stock_path=enriched_stock_path,
        technology_catalog_path=baseline_case_dir / "aviation_technology_catalog.csv",
        scenario_table_path=baseline_case_dir / "aviation_scenario.csv",
        output_dir=tmp_path,
        config=OpenAPFuelConfig(include_non_co2=False),
    )
    profiles = build_openap_activity_profiles(outputs.flight_results)

    assert (tmp_path / "openap_flight_fuel_emissions.csv").exists()
    assert (tmp_path / "openap_aircraft_type_summary.csv").exists()
    assert (tmp_path / "openap_route_summary.csv").exists()
    assert (tmp_path / "openap_aircraft_type_mapping_log.csv").exists()
    assert (tmp_path / "openap_validation_report.txt").exists()
    assert not outputs.flight_results.empty
    assert not outputs.aircraft_type_summary.empty
    assert not outputs.route_summary.empty
    assert (outputs.flight_results["fuel_kg"] > 0.0).all()
    assert (outputs.flight_results["passenger_payload_kg"] > 0.0).any()
    assert (outputs.flight_results["estimated_block_fuel_kg"] > 0.0).any()
    assert {"aircraft_type", "total_fuel_kg", "baseline_energy_demand"}.issubset(profiles.columns)


def test_stock_matching_enriches_registration_icao24_and_german_flag(tmp_path: Path) -> None:
    repo_root = _repo_root()
    stock_path = _passenger_case_dir() / "aviation_fleet_stock.csv"
    raw_opensky_path = (
        repo_root
        / "data"
        / "examples"
        / "aviation_preprocessing"
        / "opensky_aircraft_db_sample.csv"
    )

    cleaned_stock = AviationStockCleaner().clean(stock_path)
    processed_db = OpenSkyAircraftDatabaseProcessor().process(
        raw_opensky_path,
        output_path=tmp_path / "opensky_aircraft_db_processed.csv",
    )
    match_result = AviationStockMatcher().match(cleaned_stock, processed_db)

    lufthansa_row = match_result.enriched_stock.loc[
        match_result.enriched_stock["aircraft_id"] == 321,
    ].iloc[0]
    eurowings_row = match_result.enriched_stock.loc[
        match_result.enriched_stock["aircraft_id"] == 7101,
    ].iloc[0]

    assert lufthansa_row["registration"] == "D-AIAB"
    assert lufthansa_row["icao24"] == "3c6444"
    assert bool(lufthansa_row["is_german_flag"]) is True
    assert lufthansa_row["match_method"] == "exact_multi_feature"
    assert eurowings_row["registration"] == "D-AIXA"
    assert eurowings_row["match_status"] == "matched"

    german_flag = filter_german_flag_fleet(match_result.enriched_stock)
    assert {"D-AIAB", "D-AIXA"}.issubset(set(german_flag["registration"]))
    assert {
        "exact_matches",
        "high_confidence_matches",
        "ambiguous_matches",
        "unmatched_rows",
        "total_rows",
    } == set(match_result.report["metric"])


def test_flightlist_ingestion_activity_profiles_and_allocation_pipeline(tmp_path: Path) -> None:
    repo_root = _repo_root()
    example_root = repo_root / "data" / "examples" / "aviation_preprocessing"
    raw_opensky_path = example_root / "opensky_aircraft_db_sample.csv"
    airports_path = example_root / "airports_sample.csv"
    flightlist_dir = example_root / "opensky_flightlists"

    processed_db_path = tmp_path / "opensky_aircraft_db_processed.csv"
    processed_db = OpenSkyAircraftDatabaseProcessor().process(
        raw_opensky_path,
        output_path=processed_db_path,
    )
    ingestor = OpenSkyFlightlistIngestor(
        FlightlistIngestionConfig(
            input_folder=flightlist_dir,
            output_parquet_path=tmp_path / "opensky_flightlist_processed.parquet",
            airport_metadata_path=airports_path,
            year_start=2022,
            year_end=2022,
        ),
    )
    processed_flights = ingestor.ingest()
    activity_outputs = AviationActivityProfileBuilder(airport_metadata_path=airports_path).build(
        processed_flightlist_path=tmp_path / "opensky_flightlist_processed.parquet",
        aircraft_db_processed_path=processed_db_path,
        output_dir=tmp_path,
    )
    allocation_outputs = AviationAllocationBuilder(airport_metadata_path=airports_path).build(
        processed_flightlist_path=tmp_path / "opensky_flightlist_processed.parquet",
        aircraft_db_processed_path=processed_db_path,
        output_dir=tmp_path,
    )

    assert not processed_flights.empty
    assert (tmp_path / "opensky_flightlist_processed.parquet").exists()
    assert not activity_outputs.by_type.empty
    assert not activity_outputs.by_operator_type.empty
    assert not activity_outputs.by_airport_type.empty
    assert not activity_outputs.by_registration.empty
    assert (activity_outputs.by_type["annual_departures"] > 0).all()
    assert (activity_outputs.by_type["average_route_distance_km"] > 0).all()
    assert not allocation_outputs.airport_allocation.empty
    assert "share_airport_within_type" in allocation_outputs.airport_allocation.columns
    german_departures = filter_german_airport_departures(
        processed_flights.assign(origin_country="Germany")
    )
    assert not german_departures.empty
    assert {"Lufthansa", "Eurowings"}.issubset(
        set(activity_outputs.by_operator_type["operator_name"])
    )
    assert not processed_db.empty


def test_enriched_activity_profiles_merge_into_case_and_fleet(tmp_path: Path) -> None:
    repo_root = _repo_root()
    example_root = repo_root / "data" / "examples" / "aviation_preprocessing"
    baseline_case_dir = _passenger_case_dir()

    stock_path = baseline_case_dir / "aviation_fleet_stock.csv"
    raw_opensky_path = example_root / "opensky_aircraft_db_sample.csv"
    airports_path = example_root / "airports_sample.csv"
    flightlist_dir = example_root / "opensky_flightlists"

    processed_db_path = tmp_path / "opensky_aircraft_db_processed.csv"
    processed_db = OpenSkyAircraftDatabaseProcessor().process(
        raw_opensky_path,
        output_path=processed_db_path,
    )
    cleaned_stock = AviationStockCleaner().clean(stock_path)
    match_result = AviationStockMatcher().match(cleaned_stock, processed_db)
    matched_stock_path = tmp_path / "aviation_fleet_stock_matched.csv"
    match_result.enriched_stock.to_csv(matched_stock_path, index=False)

    OpenSkyFlightlistIngestor(
        FlightlistIngestionConfig(
            input_folder=flightlist_dir,
            output_parquet_path=tmp_path / "opensky_flightlist_processed.parquet",
            airport_metadata_path=airports_path,
            year_start=2022,
            year_end=2022,
        ),
    ).ingest()
    AviationActivityProfileBuilder(airport_metadata_path=airports_path).build(
        processed_flightlist_path=tmp_path / "opensky_flightlist_processed.parquet",
        aircraft_db_processed_path=processed_db_path,
        output_dir=tmp_path,
    )

    outputs = AviationBaselineBuilder().build(
        stock_input_path=matched_stock_path,
        registration_profiles_path=tmp_path / "aviation_activity_profiles_by_registration.csv",
        operator_type_profiles_path=tmp_path / "aviation_activity_profiles_by_operator_type.csv",
        type_profiles_path=tmp_path / "aviation_activity_profiles_by_type.csv",
        technology_catalog_path=baseline_case_dir / "aviation_technology_catalog.csv",
        output_stock_path=tmp_path / "aviation_fleet_stock_enriched.csv",
        output_activity_profiles_path=tmp_path / "aviation_activity_profiles.csv",
    )

    case_dir = tmp_path / "baseline-passenger-transition"
    case_dir.mkdir()
    for filename in ("scenario.yaml", "aviation_technology_catalog.csv", "aviation_scenario.csv"):
        shutil.copy2(baseline_case_dir / filename, case_dir / filename)
    shutil.copy2(
        tmp_path / "aviation_fleet_stock_enriched.csv", case_dir / "aviation_fleet_stock.csv"
    )
    shutil.copy2(
        tmp_path / "aviation_activity_profiles.csv", case_dir / "aviation_activity_profiles.csv"
    )

    case_data = AviationPassengerCaseData.from_directory(case_dir)
    lufthansa_row = case_data.fleet.loc[case_data.fleet["registration"] == "D-AIAB"].iloc[0]

    assert not outputs.enriched_stock.empty
    assert not outputs.activity_profiles.empty
    assert pd.notna(lufthansa_row["annual_distance_km_base"])
    assert pd.notna(lufthansa_row["baseline_energy_demand"])
    assert lufthansa_row["activity_assignment_method"] == "registration"

    fleet = Fleet(
        case_data.fleet.loc[case_data.fleet["operator_name"] == "Lufthansa"].copy(),
        technology_catalog=TechnologyCatalog.from_csv(
            baseline_case_dir / "aviation_technology_catalog.csv",
        ),
        start_year=2025,
    )
    aircraft = fleet.frame.loc[fleet.frame["registration"] == "D-AIAB"].iloc[0]
    technology_row = fleet.technology_row(
        technology_name=str(aircraft["current_technology"]),
        segment=str(aircraft["segment"]),
    )
    assert fleet.annual_distance_km_for(aircraft, technology_row) > 0.0
    assert fleet.baseline_energy_demand_for(aircraft, technology_row) > 0.0


def test_zero_activity_profile_values_fall_back_to_fleet_defaults() -> None:
    case_dir = _passenger_case_dir()
    case_data = AviationPassengerCaseData.from_directory(case_dir)
    technology_catalog = TechnologyCatalog.from_csv(case_dir / "aviation_technology_catalog.csv")
    fleet = Fleet(
        case_data.fleet.loc[case_data.fleet["operator_name"] == "Ryanair"].copy(),
        technology_catalog=technology_catalog,
        start_year=2025,
    )

    assert (fleet.frame["annual_distance_km_base"] > 1_000_000.0).all()
    assert (fleet.frame["baseline_energy_demand"] > 0.0).all()
