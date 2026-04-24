from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
from navaero_transition_model.aviation_preprocessing.activity_profiles import (
    AviationActivityProfileBuilder,
)
from navaero_transition_model.aviation_preprocessing.allocation import AviationAllocationBuilder
from navaero_transition_model.aviation_preprocessing.baseline import AviationBaselineBuilder
from navaero_transition_model.aviation_preprocessing.filters import (
    filter_german_airport_departures,
    filter_german_flag_fleet,
)
from navaero_transition_model.aviation_preprocessing.flightlists import (
    FlightlistIngestionConfig,
    OpenSkyFlightlistIngestor,
)
from navaero_transition_model.aviation_preprocessing.matching import AviationStockMatcher
from navaero_transition_model.aviation_preprocessing.opensky_aircraft_db import (
    OpenSkyAircraftDatabaseProcessor,
)
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner
from navaero_transition_model.core.case_inputs import AviationPassengerCaseData, TechnologyCatalog
from navaero_transition_model.core.fleet_management import Fleet


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_stock_matching_enriches_registration_icao24_and_german_flag(tmp_path: Path) -> None:
    repo_root = _repo_root()
    stock_path = repo_root / "data" / "baseline-transition" / "aviation_fleet_stock.csv"
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
    baseline_case_dir = repo_root / "data" / "baseline-transition"

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

    case_dir = tmp_path / "baseline-transition"
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
