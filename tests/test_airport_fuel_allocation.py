from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from navaero_transition_model.postprocessing import (
    AirportFuelAllocationConfig,
    allocate_airport_fuel,
)


def _write_airports(path: Path) -> None:
    pd.DataFrame(
        [
            {"iata": "FRA", "latitude": 50.0379, "longitude": 8.5622},
            {"iata": "MUC", "latitude": 48.3538, "longitude": 11.7861},
            {"iata": "DUB", "latitude": 53.4213, "longitude": -6.2701},
        ],
    ).to_csv(path, index=False)


def _write_technology(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "technology_name": "kerosene_short",
                "primary_energy_carrier": "kerosene",
                "secondary_energy_carrier": "none",
                "saf_pathway": "",
                "drop_in_fuel": False,
                "maximum_secondary_energy_share": 0.0,
                "lifetime_years": 20,
                "payback_interest_rate": 0.05,
                "capex_eur": 1.0,
                "maintenance_cost_share": 0.1,
                "depreciation_cost_share": 0.1,
                "kilometer_per_kwh": 1.0,
                "trip_days_per_year": 300,
                "fuel_capacity_kwh": 10000.0,
                "trip_length_km": 1000.0,
                "economy_seats": 150,
                "business_seats": 0,
                "first_class_seats": 0,
                "mtow": 78000.0,
                "oew": 42000.0,
                "primary_energy_emission_factor": 1.0,
                "secondary_energy_emission_factor": 0.0,
                "hydrocarbon_factor": 0.0,
                "carbon_monoxide_factor": 0.0,
                "nitrogen_oxide_factor": 0.0,
                "smoke_number_factor": 0.0,
            },
        ],
    ).to_csv(path, index=False)


def test_airport_fuel_allocation_uses_exact_flight_sequence_when_identifiers_match(
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "results"
    processed_dir = tmp_path / "processed"
    results_dir.mkdir()
    processed_dir.mkdir()
    airports_path = tmp_path / "airports.csv"
    technology_path = tmp_path / "technology.csv"
    _write_airports(airports_path)
    _write_technology(technology_path)

    pd.DataFrame(
        [
            {
                "year": 2030,
                "sector_name": "aviation",
                "aircraft_id": "A1",
                "icao24": "abc123",
                "registration": "D-TEST",
                "operator_name": "Example Air",
                "aircraft_type": "A320",
                "main_hub": "Frankfurt",
                "current_technology": "kerosene_short",
                "primary_energy_carrier": "kerosene",
                "primary_energy_consumption": 3000.0,
                "secondary_energy_consumption": 0.0,
                "total_emission": 900.0,
            },
        ],
    ).to_csv(results_dir / "aircraft.csv", index=False)
    pd.DataFrame(
        [
            {
                "aircraft_id": "abc123",
                "registration": "D-TEST",
                "operator_name": "Example Air",
                "raw_aircraft_type": "A320",
                "origin": "FRA",
                "destination": "MUC",
                "date": "2022-01-01",
                "energy_mwh": 1.0,
                "fuel_kg": 100.0,
                "co2_kg": 300.0,
            },
            {
                "aircraft_id": "abc123",
                "registration": "D-TEST",
                "operator_name": "Example Air",
                "raw_aircraft_type": "A320",
                "origin": "MUC",
                "destination": "FRA",
                "date": "2022-01-01 12:00:00",
                "energy_mwh": 1.0,
                "fuel_kg": 100.0,
                "co2_kg": 300.0,
            },
        ],
    ).to_csv(processed_dir / "openap_flight_fuel_emissions.csv", index=False)

    outputs = allocate_airport_fuel(
        AirportFuelAllocationConfig(
            results_dir=results_dir,
            processed_aviation_dir=processed_dir,
            airport_metadata_path=airports_path,
            technology_catalog_path=technology_path,
            reserve_factor=1.15,
        ),
    )

    assert set(outputs.airport_fuel_demand["allocation_method"]) == {"flightlist_sequence"}
    airport_uplift = dict(
        zip(
            outputs.airport_fuel_demand["airport"],
            outputs.airport_fuel_demand["fuel_uplift_mwh"],
            strict=True,
        ),
    )
    assert airport_uplift["FRA"] == pytest.approx(1.725)
    assert airport_uplift["MUC"] == 1.5
    assert outputs.route_energy_flow["trips"].sum() == 2.0
    assert (results_dir / "airport_fuel_demand.csv").exists()
    assert (results_dir / "route_energy_flow.csv").exists()


def test_airport_fuel_allocation_falls_back_to_synthetic_route_shares(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    processed_dir = tmp_path / "processed"
    results_dir.mkdir()
    processed_dir.mkdir()
    airports_path = tmp_path / "airports.csv"
    technology_path = tmp_path / "technology.csv"
    _write_airports(airports_path)
    _write_technology(technology_path)

    pd.DataFrame(
        [
            {
                "year": 2030,
                "sector_name": "aviation",
                "aircraft_id": "A1",
                "operator_name": "Example Air",
                "aircraft_type": "A320",
                "main_hub": "Frankfurt",
                "current_technology": "kerosene_short",
                "primary_energy_carrier": "kerosene",
                "primary_energy_consumption": 2000.0,
                "secondary_energy_consumption": 0.0,
                "total_emission": 600.0,
            },
        ],
    ).to_csv(results_dir / "aircraft.csv", index=False)
    pd.DataFrame(
        [
            {
                "origin": "FRA",
                "destination": "DUB",
                "number_of_trips": 1,
                "total_energy_mwh": 2.0,
                "total_co2_kg": 600.0,
            },
        ],
    ).to_csv(processed_dir / "openap_route_summary.csv", index=False)

    outputs = allocate_airport_fuel(
        AirportFuelAllocationConfig(
            results_dir=results_dir,
            processed_aviation_dir=processed_dir,
            airport_metadata_path=airports_path,
            technology_catalog_path=technology_path,
        ),
    )

    assert set(outputs.airport_fuel_demand["allocation_method"]) == {"synthetic_route_share"}
    assert outputs.airport_fuel_demand.iloc[0]["airport"] == "FRA"
    assert outputs.airport_fuel_demand.iloc[0]["fuel_uplift_mwh"] == 2.0
    assert outputs.route_energy_flow.iloc[0]["origin_airport"] == "FRA"
    assert outputs.route_energy_flow.iloc[0]["destination_airport"] == "DUB"
