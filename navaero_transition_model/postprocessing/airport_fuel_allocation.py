from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROCESSED_AVIATION_DIR = PROJECT_ROOT / "data" / "processed" / "aviation"
DEFAULT_AIRPORT_METADATA = (
    PROJECT_ROOT / "data" / "examples" / "aviation_preprocessing" / "airports_sample.csv"
)
JET_A_KWH_PER_KG = 43.0 / 3.6

HUB_AIRPORT_ALIASES = {
    "dublin": "DUB",
    "dusseldorf": "DUS",
    "duesseldorf": "DUS",
    "frankfurt": "FRA",
    "munich": "MUC",
    "paris cdg": "CDG",
}

EXTRA_AIRPORT_COORDS = pd.DataFrame(
    [
        {"airport": "DUS", "lat": 51.2895, "lon": 6.7668},
    ],
)


@dataclass(frozen=True)
class AirportFuelAllocationConfig:
    results_dir: Path
    processed_aviation_dir: Path = DEFAULT_PROCESSED_AVIATION_DIR
    airport_metadata_path: Path = DEFAULT_AIRPORT_METADATA
    technology_catalog_path: Path | None = None
    output_dir: Path | None = None
    reserve_factor: float = 1.15


@dataclass(frozen=True)
class AirportFuelAllocationOutputs:
    airport_fuel_demand: pd.DataFrame
    route_energy_flow: pd.DataFrame
    allocation_summary: pd.DataFrame


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _hub_to_airport(value: object) -> str:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return HUB_AIRPORT_ALIASES.get(text.lower(), text.upper())


def _normalize_type(value: object) -> str:
    text = str(value).upper().strip()
    for token in ("AIRBUS", "BOEING", "-", " "):
        text = text.replace(token, "")
    return text[:4]


def _airport_coordinates(path: Path) -> pd.DataFrame:
    airports = _read_csv(path)
    if airports.empty:
        return EXTRA_AIRPORT_COORDS.copy()
    airports = airports.rename(
        columns={
            "iata": "airport",
            "airport_code": "airport",
            "latitude": "lat",
            "latitude_deg": "lat",
            "longitude": "lon",
            "longitude_deg": "lon",
        },
    )
    if not {"airport", "lat", "lon"}.issubset(airports.columns):
        return EXTRA_AIRPORT_COORDS.copy()
    airports["lat"] = _numeric(airports["lat"])
    airports["lon"] = _numeric(airports["lon"])
    return (
        pd.concat([airports[["airport", "lat", "lon"]], EXTRA_AIRPORT_COORDS], ignore_index=True)
        .dropna()
        .drop_duplicates("airport")
    )


def _candidate_technology_catalogs() -> list[Path]:
    return sorted((PROJECT_ROOT / "data").glob("*/aviation_technology_catalog.csv"))


def _technology_catalog(path: Path | None, technology_names: set[str]) -> pd.DataFrame:
    paths = [path] if path is not None else _candidate_technology_catalogs()
    for candidate in paths:
        if candidate is None or not candidate.exists():
            continue
        catalog = _read_csv(candidate)
        if catalog.empty or "technology_name" not in catalog.columns:
            continue
        names = set(catalog["technology_name"].dropna().astype(str))
        if path is not None or technology_names.issubset(names):
            return catalog
    return pd.DataFrame()


def _aircraft_context(config: AirportFuelAllocationConfig) -> pd.DataFrame:
    aircraft = _read_csv(config.results_dir / "aircraft.csv")
    if aircraft.empty:
        return aircraft
    aircraft = aircraft.copy()
    if "sector_name" in aircraft.columns:
        aircraft = aircraft.loc[aircraft["sector_name"].astype(str).str.lower().eq("aviation")]
    if aircraft.empty:
        return aircraft

    technology_names = set(aircraft.get("current_technology", pd.Series(dtype=str)).astype(str))
    catalog = _technology_catalog(config.technology_catalog_path, technology_names)
    if not catalog.empty:
        technology_columns = [
            column
            for column in (
                "technology_name",
                "fuel_capacity_kwh",
                "primary_energy_carrier",
                "secondary_energy_carrier",
                "saf_pathway",
            )
            if column in catalog.columns
        ]
        aircraft = aircraft.merge(
            catalog[technology_columns].rename(columns={"technology_name": "current_technology"}),
            on="current_technology",
            how="left",
            suffixes=("", "_technology"),
        )

    primary = _numeric(
        aircraft.get("primary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
    )
    secondary = _numeric(
        aircraft.get("secondary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
    )
    aircraft["simulated_energy_kwh"] = primary + secondary
    aircraft["co2"] = _numeric(aircraft.get("total_emission", pd.Series(0.0, index=aircraft.index)))
    aircraft["carrier"] = (
        aircraft.get("primary_energy_carrier", pd.Series("unknown", index=aircraft.index))
        .fillna("unknown")
        .astype(str)
        .str.lower()
    )
    if "fuel_capacity_kwh" not in aircraft.columns:
        aircraft["fuel_capacity_kwh"] = pd.NA
    aircraft["fuel_capacity_kwh"] = pd.to_numeric(aircraft["fuel_capacity_kwh"], errors="coerce")
    aircraft["aircraft_key"] = aircraft["aircraft_id"].astype(str)
    if "icao24" in aircraft.columns:
        aircraft["icao24_key"] = aircraft["icao24"].fillna("").astype(str).str.lower()
    else:
        aircraft["icao24_key"] = ""
    if "registration" in aircraft.columns:
        aircraft["registration_key"] = aircraft["registration"].fillna("").astype(str).str.upper()
    else:
        aircraft["registration_key"] = ""
    hub_col = "main_hub_base" if "main_hub_base" in aircraft.columns else "main_hub"
    aircraft["airport"] = aircraft.get(
        hub_col,
        pd.Series("", index=aircraft.index),
    ).map(_hub_to_airport)
    aircraft["type_key"] = aircraft.get("aircraft_type", pd.Series("", index=aircraft.index)).map(
        _normalize_type,
    )
    return aircraft


def _flight_results(config: AirportFuelAllocationConfig) -> pd.DataFrame:
    flight_results = _read_csv(config.processed_aviation_dir / "openap_flight_fuel_emissions.csv")
    if flight_results.empty:
        flight_results = _read_table(
            config.processed_aviation_dir / "opensky_flightlist_processed.parquet",
        )
    if flight_results.empty:
        return flight_results
    flight_results = flight_results.copy()
    flight_results["origin"] = (
        flight_results.get("origin", pd.Series("", index=flight_results.index))
        .astype(str)
        .str.upper()
    )
    flight_results["destination"] = (
        flight_results.get("destination", pd.Series("", index=flight_results.index))
        .astype(str)
        .str.upper()
    )
    flight_results["carrier"] = (
        flight_results.get(
            "primary_energy_carrier",
            pd.Series("kerosene", index=flight_results.index),
        )
        .fillna("kerosene")
        .astype(str)
        .str.lower()
    )
    flight_results["fuel_kg"] = _numeric(
        flight_results.get("fuel_kg", pd.Series(0.0, index=flight_results.index)),
    )
    if "energy_mwh" in flight_results.columns:
        flight_results["energy_kwh"] = _numeric(flight_results["energy_mwh"]) * 1000.0
    else:
        flight_results["energy_kwh"] = flight_results["fuel_kg"] * JET_A_KWH_PER_KG
    flight_results["co2"] = _numeric(
        flight_results.get("co2_kg", pd.Series(0.0, index=flight_results.index)),
    )
    if "firstseen" in flight_results.columns:
        flight_results["sequence_time"] = pd.to_datetime(
            flight_results["firstseen"],
            errors="coerce",
        )
    elif "date" in flight_results.columns:
        flight_results["sequence_time"] = pd.to_datetime(flight_results["date"], errors="coerce")
    else:
        flight_results["sequence_time"] = pd.NaT
    flight_results["icao24_key"] = (
        flight_results.get(
            "aircraft_id",
            flight_results.get("icao24", pd.Series("", index=flight_results.index)),
        )
        .fillna("")
        .astype(str)
        .str.lower()
    )
    flight_results["registration_key"] = (
        flight_results.get("registration", pd.Series("", index=flight_results.index))
        .fillna("")
        .astype(str)
        .str.upper()
    )
    flight_results["operator_name"] = (
        flight_results.get("operator_name", pd.Series("", index=flight_results.index))
        .fillna("")
        .astype(str)
        .str.strip()
    )
    flight_results["type_key"] = flight_results.get(
        "raw_aircraft_type",
        flight_results.get("typecode", pd.Series("", index=flight_results.index)),
    ).map(_normalize_type)
    return flight_results


def _exact_sequence_allocations(
    aircraft: pd.DataFrame,
    flights: pd.DataFrame,
    config: AirportFuelAllocationConfig,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    if aircraft.empty or flights.empty:
        return pd.DataFrame()

    matched_aircraft_indices: set[int] = set()
    for key_column in ("icao24_key", "registration_key"):
        usable_aircraft = aircraft.loc[
            aircraft[key_column].astype(str).str.strip().ne("")
            & ~aircraft.index.isin(matched_aircraft_indices)
        ]
        usable_flights = flights.loc[flights[key_column].astype(str).str.strip().ne("")]
        if usable_aircraft.empty or usable_flights.empty:
            continue
        grouped_flights = {
            key: frame.sort_values("sequence_time")
            for key, frame in usable_flights.groupby(key_column, dropna=False)
        }
        for _, aircraft_row in usable_aircraft.iterrows():
            key = aircraft_row[key_column]
            sequence = grouped_flights.get(key)
            if sequence is None or sequence.empty:
                continue
            baseline_energy = float(sequence["energy_kwh"].sum())
            simulated_energy = float(aircraft_row.get("simulated_energy_kwh", 0.0) or 0.0)
            if baseline_energy <= 0.0 or simulated_energy <= 0.0:
                continue
            matched_aircraft_indices.add(int(aircraft_row.name))
            scale = simulated_energy / baseline_energy
            capacity = pd.to_numeric(
                pd.Series([aircraft_row.get("fuel_capacity_kwh", pd.NA)]),
                errors="coerce",
            ).iloc[0]
            capacity_kwh = float(capacity) if pd.notna(capacity) and float(capacity) > 0 else None
            onboard_kwh = 0.0
            previous_destination = ""
            for _, flight in sequence.iterrows():
                origin = str(flight["origin"]).upper()
                destination = str(flight["destination"]).upper()
                if previous_destination and previous_destination != origin:
                    onboard_kwh = 0.0
                required_kwh = float(flight["energy_kwh"]) * scale
                target_kwh = required_kwh * config.reserve_factor
                capacity_exceeded = False
                if capacity_kwh is not None and target_kwh > capacity_kwh:
                    target_kwh = capacity_kwh
                    capacity_exceeded = True
                uplift_kwh = max(target_kwh - onboard_kwh, 0.0)
                onboard_kwh = max(target_kwh - required_kwh, 0.0)
                records.append(
                    {
                        "year": int(aircraft_row["year"]),
                        "aircraft_id": aircraft_row.get("aircraft_id", ""),
                        "origin_airport": origin,
                        "destination_airport": destination,
                        "airport": origin,
                        "carrier": aircraft_row.get("carrier", "unknown"),
                        "allocation_method": "flightlist_sequence",
                        "energy_demand_kwh": required_kwh,
                        "fuel_uplift_kwh": uplift_kwh,
                        "co2": float(flight.get("co2", 0.0)) * scale,
                        "trips": 1.0,
                        "fuel_capacity_kwh": capacity_kwh,
                        "capacity_exceeded": capacity_exceeded,
                    },
                )
                previous_destination = destination
    return pd.DataFrame.from_records(records)


def _route_templates(processed_dir: Path) -> pd.DataFrame:
    route_summary = _read_csv(processed_dir / "openap_route_summary.csv")
    if not route_summary.empty:
        routes = route_summary.rename(
            columns={
                "origin": "origin_airport",
                "destination": "destination_airport",
                "number_of_trips": "baseline_trips",
                "total_energy_mwh": "baseline_energy_mwh",
                "total_co2_kg": "baseline_co2",
            },
        )
        return routes
    flights = _flight_results(
        AirportFuelAllocationConfig(results_dir=Path("."), processed_aviation_dir=processed_dir),
    )
    if flights.empty:
        return pd.DataFrame()
    return (
        flights.groupby(["origin", "destination"], as_index=False)
        .agg(
            baseline_trips=("origin", "size"),
            baseline_energy_mwh=("energy_kwh", lambda values: values.sum() / 1000.0),
            baseline_co2=("co2", "sum"),
        )
        .rename(columns={"origin": "origin_airport", "destination": "destination_airport"})
    )


def _synthetic_allocations(
    aircraft: pd.DataFrame,
    route_templates: pd.DataFrame,
) -> pd.DataFrame:
    if aircraft.empty:
        return pd.DataFrame()
    airport_rows = aircraft.loc[aircraft["simulated_energy_kwh"] > 0.0].copy()
    if airport_rows.empty:
        return pd.DataFrame()
    airport_rows["capacity_exceeded"] = False
    airport_rows = airport_rows.groupby(
        ["year", "airport", "carrier"],
        dropna=False,
        as_index=False,
    ).agg(
        simulated_energy_kwh=("simulated_energy_kwh", "sum"),
        co2=("co2", "sum"),
        trips=("aircraft_id", "count"),
        fuel_capacity_kwh=("fuel_capacity_kwh", "max"),
        capacity_exceeded=("capacity_exceeded", "sum"),
    )

    route_records: list[dict[str, object]] = []
    route_templates = route_templates.copy()
    if not route_templates.empty:
        route_templates["origin_airport"] = (
            route_templates["origin_airport"].astype(str).str.upper()
        )
        route_templates["destination_airport"] = (
            route_templates["destination_airport"].astype(str).str.upper()
        )

    for _, row in airport_rows.iterrows():
        origin = str(row.get("airport", "")).upper()
        if not origin:
            continue
        outgoing = route_templates.loc[route_templates["origin_airport"].eq(origin)]
        if outgoing.empty:
            route_records.append(
                {
                    "year": int(row["year"]),
                    "aircraft_id": row.get("aircraft_id", ""),
                    "origin_airport": origin,
                    "destination_airport": "",
                    "airport": origin,
                    "carrier": row.get("carrier", "unknown"),
                    "allocation_method": "synthetic_airport_share",
                    "energy_demand_kwh": float(row["simulated_energy_kwh"]),
                    "fuel_uplift_kwh": float(row["simulated_energy_kwh"]),
                    "co2": float(row.get("co2", 0.0) or 0.0),
                    "trips": float(row.get("trips", 0.0) or 0.0),
                    "fuel_capacity_kwh": row.get("fuel_capacity_kwh", pd.NA),
                    "capacity_exceeded": False,
                },
            )
            continue
        weights = _numeric(
            outgoing.get("baseline_energy_mwh", pd.Series(1.0, index=outgoing.index)),
            default=1.0,
        )
        if float(weights.sum()) <= 0.0:
            weights = pd.Series(1.0, index=outgoing.index)
        shares = weights / float(weights.sum())
        for route_index, route in outgoing.iterrows():
            share = float(shares.loc[route_index])
            route_records.append(
                {
                    "year": int(row["year"]),
                    "aircraft_id": row.get("aircraft_id", ""),
                    "origin_airport": origin,
                    "destination_airport": route["destination_airport"],
                    "airport": origin,
                    "carrier": row.get("carrier", "unknown"),
                    "allocation_method": "synthetic_route_share",
                    "energy_demand_kwh": float(row["simulated_energy_kwh"]) * share,
                    "fuel_uplift_kwh": float(row["simulated_energy_kwh"]) * share,
                    "co2": float(row.get("co2", 0.0) or 0.0) * share,
                    "trips": float(row.get("trips", 0.0) or 0.0) * share,
                    "fuel_capacity_kwh": row.get("fuel_capacity_kwh", pd.NA),
                    "capacity_exceeded": False,
                },
            )
    return pd.DataFrame.from_records(route_records)


def _with_coordinates(
    frame: pd.DataFrame,
    coords: pd.DataFrame,
    *,
    airport_column: str,
    prefix: str = "",
) -> pd.DataFrame:
    if frame.empty or airport_column not in frame.columns:
        return frame
    renamed = coords.rename(
        columns={
            "airport": airport_column,
            "lat": f"{prefix}lat",
            "lon": f"{prefix}lon",
        },
    )
    return frame.merge(renamed, on=airport_column, how="left")


def _finalize_outputs(records: pd.DataFrame, coords: pd.DataFrame) -> AirportFuelAllocationOutputs:
    if records.empty:
        empty_airports = pd.DataFrame()
        empty_routes = pd.DataFrame()
        summary = pd.DataFrame([{"allocation_method": "none", "records": 0}])
        return AirportFuelAllocationOutputs(empty_airports, empty_routes, summary)

    records = records.copy()
    records["fuel_uplift_mwh"] = records["fuel_uplift_kwh"] / 1000.0
    records["energy_demand"] = records["energy_demand_kwh"] / 1000.0
    records["fuel_uplift_kg"] = records["fuel_uplift_kwh"] / JET_A_KWH_PER_KG
    records["fuel_demand"] = records["fuel_uplift_mwh"]

    airport_group = [
        "year",
        "airport",
        "carrier",
        "allocation_method",
    ]
    airports = (
        records.groupby(airport_group, dropna=False, as_index=False)
        .agg(
            fuel_demand=("fuel_demand", "sum"),
            fuel_uplift_mwh=("fuel_uplift_mwh", "sum"),
            fuel_uplift_kg=("fuel_uplift_kg", "sum"),
            energy_demand=("energy_demand", "sum"),
            co2=("co2", "sum"),
            trips=("trips", "sum"),
            capacity_exceeded_count=("capacity_exceeded", "sum"),
        )
        .pipe(_with_coordinates, coords, airport_column="airport")
    )

    route_group = [
        "year",
        "origin_airport",
        "destination_airport",
        "carrier",
        "allocation_method",
    ]
    routes = records.groupby(route_group, dropna=False, as_index=False).agg(
        energy_demand=("energy_demand", "sum"),
        fuel_uplift_mwh=("fuel_uplift_mwh", "sum"),
        fuel_uplift_kg=("fuel_uplift_kg", "sum"),
        co2=("co2", "sum"),
        trips=("trips", "sum"),
        capacity_exceeded_count=("capacity_exceeded", "sum"),
    )
    routes = _with_coordinates(routes, coords, airport_column="origin_airport", prefix="origin_")
    routes = _with_coordinates(
        routes,
        coords,
        airport_column="destination_airport",
        prefix="destination_",
    )
    routes = routes.dropna(
        subset=["origin_lat", "origin_lon", "destination_lat", "destination_lon"],
        how="any",
    )
    summary = records.groupby("allocation_method", as_index=False).agg(
        records=("allocation_method", "size"),
        fuel_uplift_mwh=("fuel_uplift_mwh", "sum"),
        capacity_exceeded_count=("capacity_exceeded", "sum"),
    )
    return AirportFuelAllocationOutputs(airports, routes, summary)


def allocate_airport_fuel(config: AirportFuelAllocationConfig) -> AirportFuelAllocationOutputs:
    aircraft = _aircraft_context(config)
    coords = _airport_coordinates(config.airport_metadata_path)
    flights = _flight_results(config)
    exact = _exact_sequence_allocations(aircraft, flights, config)
    if exact.empty:
        records = _synthetic_allocations(aircraft, _route_templates(config.processed_aviation_dir))
    else:
        matched_ids = set(exact["aircraft_id"].astype(str))
        unmatched_aircraft = aircraft.loc[~aircraft["aircraft_id"].astype(str).isin(matched_ids)]
        fallback = _synthetic_allocations(
            unmatched_aircraft,
            _route_templates(config.processed_aviation_dir),
        )
        records = pd.concat([exact, fallback], ignore_index=True)

    outputs = _finalize_outputs(records, coords)
    output_dir = config.output_dir or config.results_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs.airport_fuel_demand.to_csv(output_dir / "airport_fuel_demand.csv", index=False)
    outputs.route_energy_flow.to_csv(output_dir / "route_energy_flow.csv", index=False)
    outputs.allocation_summary.to_csv(
        output_dir / "airport_fuel_allocation_summary.csv",
        index=False,
    )
    return outputs
