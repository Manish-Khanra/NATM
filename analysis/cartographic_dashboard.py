from __future__ import annotations

import functools
import json
import os
import re
from pathlib import Path

import altair as alt
import pandas as pd

try:
    import solara
except ModuleNotFoundError as exc:  # pragma: no cover
    missing_package = exc.name or "dashboard dependency"
    raise RuntimeError(
        "Dashboard dependencies are missing. Install them with "
        "`python -m pip install -e .[dashboard]` before running this example. "
        f"Missing package: {missing_package}",
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / "data" / "output"
AIRPORT_METADATA_PATH = (
    ROOT / "data" / "raw" / "aviation_preprocessing" / "airports_sample.csv"
)
METRIC_METADATA = {
    "fuel_uplift_mwh": {
        "label": "Fuel uplift energy",
        "unit": "MWh",
        "large_unit": "TWh",
        "large_factor": 1_000_000.0,
        "large_threshold": 1_000.0,
    },
    "fuel_demand": {
        "label": "Fuel demand",
        "unit": "MWh",
        "large_unit": "TWh",
        "large_factor": 1_000_000.0,
        "large_threshold": 1_000.0,
    },
    # kWh, not MWh: primary/secondary_energy_consumption are in kWh, confirmed
    # against the technology catalog's emission factors, which are defined per
    # kWh (kerosene 0.2636 kg CO2/kWh reproduces total_emission exactly for
    # aircraft burning only primary fuel). These were previously labelled MWh,
    # which overstated every displayed energy figure by 1000x.
    "energy_demand": {
        "label": "Energy demand",
        "unit": "kWh",
        "large_unit": "TWh",
        "large_factor": 1_000_000_000.0,
        "large_threshold": 1_000_000.0,
    },
    "fuel_uplift_kg": {
        "label": "Fuel uplift mass",
        "unit": "kg",
        "large_unit": "tonnes",
        "large_factor": 1_000.0,
    },
    "electricity_demand": {
        "label": "Electricity demand",
        "unit": "kWh",
        "large_unit": "TWh",
        "large_factor": 1_000_000_000.0,
        "large_threshold": 1_000_000.0,
    },
    "trips": {"label": "Trips", "unit": "trips"},
    "co2": {
        "label": "CO2 emissions",
        "unit": "kg CO2",
        "large_unit": "tonnes CO2",
        "large_factor": 1_000.0,
    },
    "h2o": {
        "label": "H2O emissions",
        "unit": "kg H2O",
        "large_unit": "tonnes H2O",
        "large_factor": 1_000.0,
    },
    "nox": {
        "label": "NOx emissions",
        "unit": "kg NOx",
        "large_unit": "tonnes NOx",
        "large_factor": 1_000.0,
    },
    "co": {
        "label": "CO emissions",
        "unit": "kg CO",
        "large_unit": "tonnes CO",
        "large_factor": 1_000.0,
    },
    "hc": {
        "label": "HC emissions",
        "unit": "kg HC",
        "large_unit": "tonnes HC",
        "large_factor": 1_000.0,
    },
    "soot": {
        "label": "Soot emissions",
        "unit": "kg soot",
        "large_unit": "tonnes soot",
        "large_factor": 1_000.0,
    },
    "sox": {
        "label": "SOx emissions",
        "unit": "kg SOx",
        "large_unit": "tonnes SOx",
        "large_factor": 1_000.0,
    },
}
LARGE_METRIC_THRESHOLD = 100_000.0
AUTO_UNIT_OPTION = "Auto"

# Results folders are named "<family>-<scenario>-<attitude>", e.g.
# "baseline-cargo-transition-fokush2-risk-neutral". Splitting on that suffix
# gives the set of sibling runs that differ only by scenario -- the runs worth
# plotting against each other.
SCENARIO_SUFFIX_PATTERN = re.compile(
    r"-(aktuellepolitiken|fokush2|fokusstrom|hohenachfrage|nachfrageniedrig"
    r"|technologiemix|worstcasemean|worstcasetailrisk)"
    r"-(risk-neutral|risk-averse)$"
)
# Year totals for the trajectory chart come straight from aircraft.csv rather
# than from the map layers: reading two columns is ~15x faster than rebuilding
# every sibling's full map layers, and the totals are identical (verified --
# no hub is dropped for missing coordinates in any of the shipped families).
TRAJECTORY_METRIC_SOURCES = {
    "co2": ("total_emission",),
    "energy_demand": ("primary_energy_consumption", "secondary_energy_consumption"),
}
# Categorical slots 1-8, in the fixed order that clears the colourblind and
# normal-vision separation gates for adjacent series on a light surface
# (validated, worst adjacent CVD dE 9.1 / normal-vision dE 19.6). Assigned by
# sorted series name so a hue follows the scenario, not its position.
# Aqua/yellow/magenta fall below 3:1 against the surface, so the table view
# below the chart is required relief, not a nicety.
CATEGORICAL_PALETTE = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
)
# Which modelled energy carriers are made from electricity, and how much
# electricity each takes to make.
#
# The efficiencies are an ASSUMPTION LAYERED ON TOP OF THE MODEL, not a model
# output: the technology catalog carries vehicle efficiency (kilometer_per_kwh)
# and emission factors, but nothing about upstream conversion, so the run
# results cannot answer "how much power does this need" on their own. The
# defaults below are conventional literature values and are adjustable in the
# UI; every electricity figure shown scales directly with them.
#
# `field` is the consumption column the carrier's energy is recorded in, and
# `efficiency` is fuel energy out per unit of electricity in (both kWh).
ELECTRICITY_SOURCES = {
    "e_kerosene": {
        "label": "E-kerosene (PtL)",
        "carrier_column": "secondary_energy_carrier",
        "field": "secondary_energy_consumption",
        "efficiency": 0.48,
        "note": "power-to-liquid, electricity to finished jet fuel",
    },
    "hydrogen": {
        "label": "Renewable hydrogen",
        "carrier_column": "primary_energy_carrier",
        "field": "primary_energy_consumption",
        "efficiency": 0.68,
        "note": "electrolysis, LHV basis",
    },
    "electricity": {
        "label": "Direct electricity",
        "carrier_column": "primary_energy_carrier",
        "field": "primary_energy_consumption",
        "efficiency": 0.95,
        "note": "grid to battery, charging losses only",
    },
    "battery": {
        "label": "Direct electricity (battery)",
        "carrier_column": "secondary_energy_carrier",
        "field": "secondary_energy_consumption",
        "efficiency": 0.95,
        "note": "grid to battery, charging losses only",
    },
    # Maritime hybrid propulsion (hybrid_regional/_deepsea) records its
    # battery-assist energy as secondary_energy_carrier == "electricity" --
    # the same carrier *string* as the "electricity" entry above, but that
    # entry is scoped to primary_energy_carrier (a battery-electric vessel's
    # only fuel). A dict can't hold two keys both named "electricity", and
    # matching was previously done by treating the dict key itself as the
    # carrier string to look up, so this combination fell through both
    # existing entries silently. `match_value` decouples the two: the key is
    # a unique identifier, `match_value` is the actual string compared
    # against the column.
    "hybrid_electricity": {
        "label": "Hybrid propulsion electricity",
        "carrier_column": "secondary_energy_carrier",
        "match_value": "electricity",
        "field": "secondary_energy_consumption",
        "efficiency": 0.95,
        "note": "grid to battery, charging losses only (hybrid assist)",
    },
}

CHART_SURFACE = "#fcfcfb"
CHART_GRID = "#e1e0d9"
CHART_AXIS = "#c3c2b7"
CHART_INK_MUTED = "#898781"
CHART_INK_SECONDARY = "#52514e"
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
        # Real main_hub_base values (aircraft-level, activity-profile-derived ICAO
        # codes, preferred over the operator-level "Main Hub" city name -- see
        # hub_col = "main_hub_base" if present else "main_hub" below) covering the
        # real installed passenger + cargo fleets. airports_sample.csv is a small
        # preprocessing demo file and does not cover these.
        {"airport": "EDDF", "lat": 50.0379, "lon": 8.5622},  # Frankfurt
        {"airport": "EDDM", "lat": 48.3538, "lon": 11.7861},  # Munich
        {"airport": "EDDP", "lat": 51.4239, "lon": 12.2364},  # Leipzig/Halle
        {"airport": "EDDS", "lat": 48.6899, "lon": 9.2219},  # Stuttgart
        {"airport": "EDDL", "lat": 51.2895, "lon": 6.7668},  # Dusseldorf
        {"airport": "EDDV", "lat": 52.4611, "lon": 9.6849},  # Hannover
        {"airport": "EDFH", "lat": 49.9487, "lon": 7.2639},  # Frankfurt-Hahn
        {"airport": "EHAM", "lat": 52.3086, "lon": 4.7639},  # Amsterdam Schiphol
        {"airport": "LEPA", "lat": 39.5517, "lon": 2.7388},  # Palma de Mallorca
        # Real German maritime port coordinates. These are the AIS-derived
        # `main_hub` values produced by
        # navaero_transition_model.maritime_preprocessing.hub_assignment --
        # port names, not airport codes, so _hub_to_airport()'s uppercase
        # fallback is used verbatim as the lookup key rather than an
        # ICAO/IATA alias.
        #
        # lat/lon are the median position of that port's recorded vessel
        # visits in the Global Fishing Watch AIS data (gfw_port_visits_2024),
        # i.e. where ships actually berth -- deliberately NOT the city centre,
        # which for the river ports is far from the quays (Hamburg's berths
        # sit ~20km downstream of the Rathaus, Bremen's ~20km down the Weser).
        # Every German port name the hub-derivation can emit is listed, so a
        # refreshed AIS extract or a changed fleet cannot silently drop
        # vessels off the map for want of a coordinate.
        {"airport": "ARNIS", "lat": 54.6369, "lon": 9.9792},  # 1 AIS visits
        {"airport": "BRAKE", "lat": 53.3622, "lon": 8.4956},  # 23 AIS visits
        {"airport": "BREMEN", "lat": 53.2178, "lon": 8.6444},  # 6 AIS visits
        {"airport": "BREMERHAVEN", "lat": 53.5752, "lon": 8.5358},  # 68 AIS visits
        {"airport": "BRUNSBUTTEL", "lat": 53.8932, "lon": 9.1055},  # 459 AIS visits
        {"airport": "BUESUM", "lat": 54.1243, "lon": 8.8337},  # 8 AIS visits
        {"airport": "BURG AUF FEHMARN", "lat": 54.4104, "lon": 11.2077},  # 5 AIS visits
        {"airport": "CUXHAVEN", "lat": 53.8712, "lon": 8.7203},  # 38 AIS visits
        {"airport": "ECKERNFORDE", "lat": 54.4737, "lon": 9.8896},  # 11 AIS visits
        {"airport": "EMDEN", "lat": 53.3329, "lon": 7.1416},  # 16 AIS visits
        {"airport": "FREESENDORF", "lat": 54.1711, "lon": 13.6440},  # 19 AIS visits
        {"airport": "GLUCKSTADT", "lat": 53.8096, "lon": 9.3457},  # 1 AIS visits
        {"airport": "HAMBURG", "lat": 53.6320, "lon": 9.7355},  # 128 AIS visits
        {"airport": "HEILIGENHAFEN", "lat": 54.3893, "lon": 10.9847},  # 6 AIS visits
        {"airport": "HELGOLAND", "lat": 54.1685, "lon": 7.9032},  # 4 AIS visits
        {"airport": "HOCHDONN", "lat": 54.0420, "lon": 9.3061},  # 33 AIS visits
        {"airport": "HUSUM", "lat": 54.4749, "lon": 9.0160},  # 23 AIS visits
        {"airport": "KIEL", "lat": 54.3851, "lon": 10.1488},  # 544 AIS visits
        {"airport": "LEMWERDER", "lat": 53.2827, "lon": 8.5289},  # 5 AIS visits
        {"airport": "LUBECK", "lat": 53.9587, "lon": 10.8479},  # 15 AIS visits
        {"airport": "MUKRAN", "lat": 54.4897, "lon": 13.6604},  # 3 AIS visits
        {"airport": "NORDENHAM", "lat": 53.4934, "lon": 8.4883},  # 5 AIS visits
        {"airport": "RENDSBURG", "lat": 54.3154, "lon": 9.7071},  # 26 AIS visits
        {"airport": "ROSTOCK", "lat": 54.1843, "lon": 12.0651},  # 184 AIS visits
        {"airport": "SASSNITZ", "lat": 54.4867, "lon": 13.6657},  # 1 AIS visits
        {"airport": "STRALSUND", "lat": 54.2605, "lon": 13.2449},  # 4 AIS visits
        {"airport": "STRANDE", "lat": 54.4031, "lon": 10.1672},  # 1 AIS visits
        {"airport": "TRAVEMUENDE", "lat": 53.9714, "lon": 10.9074},  # 40 AIS visits
        {"airport": "VIEROW", "lat": 54.4258, "lon": 13.6692},  # 5 AIS visits
        {"airport": "WEWELSFLETH", "lat": 53.8517, "lon": 9.3487},  # 3 AIS visits
        {"airport": "WILHELMSHAVEN", "lat": 53.5816, "lon": 8.1370},  # 24 AIS visits
        {"airport": "WISMAR", "lat": 53.9593, "lon": 11.4112},  # 12 AIS visits
        {"airport": "WOLGAST", "lat": 54.0916, "lon": 13.7504},  # 5 AIS visits
    ]
)


def _csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def list_result_folders() -> list[str]:
    if not RESULTS_ROOT.exists():
        return []
    return sorted([p.name for p in RESULTS_ROOT.iterdir() if p.is_dir()])


@functools.lru_cache(maxsize=1)
def _openap_airport_coordinates() -> pd.DataFrame:
    """Coordinates for every airport in OpenAP's navigation database.

    The flight network reaches 745 distinct airports, but the curated sources
    below cover only a handful, and routes whose endpoints have no coordinates
    are silently dropped by the dropna() at the end of build_map_ready_layers
    -- which quietly hid 95% of routes and 88% of trips, leaving a map that
    looked like German aircraft only ever flew to Amsterdam and Mallorca.
    OpenAP is already a dependency and is what produced the route summary in
    the first place, so its own airport table is the consistent source, and it
    covers all 745 codes.
    """
    try:
        from openap import nav

        frame = pd.read_csv(nav.db_airport, usecols=["icao", "lat", "lon"])
    except Exception:
        return pd.DataFrame(columns=["airport", "lat", "lon"])
    frame = frame.rename(columns={"icao": "airport"})
    frame["airport"] = frame["airport"].astype(str).str.upper()
    frame["lat"] = pd.to_numeric(frame["lat"], errors="coerce")
    frame["lon"] = pd.to_numeric(frame["lon"], errors="coerce")
    return frame[["airport", "lat", "lon"]].dropna()


def _airport_coordinates() -> pd.DataFrame:
    airports = _csv(AIRPORT_METADATA_PATH)
    if airports.empty:
        # Curated entries first so the hand-checked seaport berth positions and
        # aliases win over any same-named row in the OpenAP table.
        return (
            pd.concat([EXTRA_AIRPORT_COORDS, _openap_airport_coordinates()], ignore_index=True)
            .dropna()
            .drop_duplicates("airport")
        )

    airports = airports.rename(
        columns={
            "iata": "airport",
            "airport_code": "airport",
            "latitude": "lat",
            "latitude_deg": "lat",
            "longitude": "lon",
            "longitude_deg": "lon",
        }
    )
    if not {"airport", "lat", "lon"}.issubset(airports.columns):
        return pd.DataFrame(columns=["airport", "lat", "lon"])

    airports["lat"] = pd.to_numeric(airports["lat"], errors="coerce")
    airports["lon"] = pd.to_numeric(airports["lon"], errors="coerce")
    return (
        pd.concat(
            [
                airports[["airport", "lat", "lon"]],
                EXTRA_AIRPORT_COORDS,
                _openap_airport_coordinates(),
            ],
            ignore_index=True,
        )
        .dropna()
        .drop_duplicates("airport")
    )


def _hub_to_airport(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return HUB_AIRPORT_ALIASES.get(text.lower(), text.upper())


def _is_maritime_run(base: Path) -> bool:
    """A maritime run writes maritime_*.csv where an aviation run writes
    aviation_*.csv. Detected from the outputs rather than the folder name so a
    renamed case still resolves correctly."""
    return any(base.glob("maritime_*.csv")) and not any(base.glob("aviation_*.csv"))


def _maritime_route_layers(airports: pd.DataFrame) -> pd.DataFrame:
    """Sea lanes out of (and into) the modelled German ports, per year.

    Built by analysis/build_maritime_routes.py from the AIS voyage record; the
    geometry follows real sea lanes rather than a great circle, so a route to
    Asia runs through the Channel and Suez instead of across Europe. Each
    port's modelled totals are spread over the voyages attributed to it, the
    same way the aviation layer spreads a hub's totals over its flights.
    """
    routes = _csv(ROOT / "data" / "processed" / "maritime" / "maritime_sea_routes.csv")
    if routes.empty or airports.empty or "year" not in airports.columns:
        return pd.DataFrame()
    if not {"from_port", "to_port", "model_port", "path"}.issubset(routes.columns):
        return pd.DataFrame()

    routes = routes.rename(
        columns={
            "from_port": "origin_airport",
            "to_port": "destination_airport",
            "from_lat": "origin_lat",
            "from_lon": "origin_lon",
            "to_lat": "destination_lat",
            "to_lon": "destination_lon",
        }
    )

    years = sorted(airports["year"].dropna().unique().tolist())
    if not years:
        return pd.DataFrame()
    routes = pd.concat([routes.assign(year=year) for year in years], ignore_index=True)

    port_totals = airports.groupby(["year", "airport"], as_index=False).agg(
        energy_demand=("energy_demand", "sum"),
        co2=("co2", "sum"),
        trips=("trips", "sum"),
    )
    route_counts = (
        routes.groupby(["year", "model_port"], as_index=False)
        .size()
        .rename(columns={"size": "port_routes"})
    )
    routes = routes.merge(
        port_totals.rename(columns={"airport": "model_port"}),
        on=["year", "model_port"],
        how="left",
    ).merge(route_counts, on=["year", "model_port"], how="left")
    routes["port_routes"] = (
        pd.to_numeric(routes["port_routes"], errors="coerce").fillna(1.0).clip(lower=1.0)
    )
    for column in ("energy_demand", "co2", "trips"):
        routes[column] = (
            pd.to_numeric(routes[column], errors="coerce").fillna(0.0) / routes["port_routes"]
        )
    return routes


def _simulated_airport_layers(
    base: Path, coords: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    aircraft = _csv(base / "aircraft.csv")
    if aircraft.empty or "year" not in aircraft.columns:
        return pd.DataFrame(), pd.DataFrame()

    hub_col = "main_hub_base" if "main_hub_base" in aircraft.columns else "main_hub"
    if hub_col not in aircraft.columns:
        return pd.DataFrame(), pd.DataFrame()

    aircraft = aircraft.copy()
    aircraft["airport"] = aircraft[hub_col].map(_hub_to_airport)
    aircraft["carrier"] = (
        aircraft.get("primary_energy_carrier", pd.Series("all", index=aircraft.index))
        .fillna("all")
        .astype(str)
        .str.lower()
    )
    aircraft["energy_demand"] = pd.to_numeric(
        aircraft.get("primary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
        errors="coerce",
    ).fillna(0.0) + pd.to_numeric(
        aircraft.get("secondary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
        errors="coerce",
    ).fillna(0.0)
    aircraft["co2"] = pd.to_numeric(
        aircraft.get("total_emission", pd.Series(0.0, index=aircraft.index)), errors="coerce"
    ).fillna(0.0)

    airports = (
        aircraft.groupby(["year", "airport", "carrier"], as_index=False)
        .agg(
            energy_demand=("energy_demand", "sum"),
            co2=("co2", "sum"),
            trips=("airport", "size"),
        )
        .merge(coords, on="airport", how="left")
    )

    # The route summary is an aviation flight network. Drawing it for a
    # maritime run put flight paths between Frankfurt, Munich and Amsterdam on
    # top of ship ports -- two transport modes on one map. Ships get their own
    # AIS-derived sea lanes instead.
    if _is_maritime_run(base):
        return airports, _maritime_route_layers(airports)

    openap_routes = _csv(ROOT / "data" / "processed" / "aviation" / "openap_route_summary.csv")
    if openap_routes.empty:
        return airports, pd.DataFrame()

    routes = openap_routes.rename(
        columns={
            "origin": "origin_airport",
            "destination": "destination_airport",
            "number_of_trips": "base_trips",
            "total_energy_mwh": "base_energy_demand",
            "total_co2_kg": "base_co2",
        }
    )
    if not {"origin_airport", "destination_airport"}.issubset(routes.columns):
        return airports, pd.DataFrame()

    years = sorted(airports["year"].dropna().unique().tolist())
    routes = pd.concat([routes.assign(year=year) for year in years], ignore_index=True)
    origin_totals = airports.groupby(["year", "airport"], as_index=False).agg(
        energy_demand=("energy_demand", "sum"),
        co2=("co2", "sum"),
        trips=("trips", "sum"),
    )
    outgoing_counts = (
        routes.groupby(["year", "origin_airport"], as_index=False)
        .size()
        .rename(columns={"size": "outgoing_routes"})
    )
    routes = routes.merge(
        origin_totals.rename(columns={"airport": "origin_airport"}),
        on=["year", "origin_airport"],
        how="left",
    ).merge(outgoing_counts, on=["year", "origin_airport"], how="left")
    routes["outgoing_routes"] = (
        pd.to_numeric(routes["outgoing_routes"], errors="coerce").fillna(1.0).clip(lower=1.0)
    )
    for col in ("energy_demand", "co2", "trips"):
        routes[col] = (
            pd.to_numeric(routes[col], errors="coerce").fillna(0.0) / routes["outgoing_routes"]
        )

    return airports, routes


def build_map_ready_layers(results_folder: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = RESULTS_ROOT / results_folder
    coords = _airport_coordinates()
    airports = _csv(base / "airport_fuel_demand.csv")
    routes = _csv(base / "route_energy_flow.csv")

    if airports.empty and routes.empty:
        airports, routes = _simulated_airport_layers(base, coords)

    if airports.empty:
        openap_airports = _csv(
            ROOT / "data" / "processed" / "aviation" / "aviation_airport_allocation.csv"
        )
        if not openap_airports.empty:
            airports = openap_airports.rename(
                columns={
                    "origin": "airport",
                    "airport_code": "airport",
                    "latitude": "lat",
                    "longitude": "lon",
                    "fuel_liters": "fuel_demand",
                    "fuel_kg": "fuel_demand",
                    "annual_departures": "trips",
                }
            )
            if {"airport", "trips"}.issubset(airports.columns):
                airports = airports.groupby("airport", as_index=False)["trips"].sum()
                airports["fuel_demand"] = airports["trips"]

    if (
        not airports.empty
        and {"airport"}.issubset(airports.columns)
        and not {"lat", "lon"}.issubset(airports.columns)
    ):
        airports = airports.merge(coords, on="airport", how="left")

    if routes.empty and not _is_maritime_run(base):
        openap_routes = _csv(ROOT / "data" / "processed" / "aviation" / "openap_route_summary.csv")
        if not openap_routes.empty:
            routes = openap_routes.rename(
                columns={
                    "origin": "origin_airport",
                    "destination": "destination_airport",
                    "trip_count": "trips",
                    "number_of_trips": "trips",
                    "fuel_kg": "energy_demand",
                    "total_fuel_kg": "fuel_demand",
                    "total_energy_mwh": "energy_demand",
                    "co2_kg": "co2",
                    "total_co2_kg": "co2",
                    "total_nox_kg": "nox",
                }
            )

    for col in (
        "lat",
        "lon",
        "fuel_demand",
        "fuel_uplift_mwh",
        "fuel_uplift_kg",
        "energy_demand",
        "co2",
        "h2o",
        "nox",
        "co",
        "hc",
        "soot",
        "sox",
        "trips",
        "year",
    ):
        if col in airports.columns:
            airports[col] = pd.to_numeric(airports[col], errors="coerce")

    for col in (
        "origin_lat",
        "origin_lon",
        "destination_lat",
        "destination_lon",
        "energy_demand",
        "fuel_uplift_mwh",
        "fuel_uplift_kg",
        "trips",
        "co2",
        "h2o",
        "nox",
        "co",
        "hc",
        "soot",
        "sox",
        "year",
    ):
        if col in routes.columns:
            routes[col] = pd.to_numeric(routes[col], errors="coerce")

    route_coords_missing = not {
        "origin_lat",
        "origin_lon",
        "destination_lat",
        "destination_lon",
    }.issubset(routes.columns)
    if (
        route_coords_missing
        and {"origin_airport", "destination_airport"}.issubset(routes.columns)
        and {"airport", "lat", "lon"}.issubset(airports.columns)
    ):
        coords = (
            pd.concat([coords, airports[["airport", "lat", "lon"]]], ignore_index=True)
            .dropna()
            .drop_duplicates("airport")
        )
        routes = routes.merge(
            coords.rename(
                columns={"airport": "origin_airport", "lat": "origin_lat", "lon": "origin_lon"}
            ),
            on="origin_airport",
            how="left",
        )
        routes = routes.merge(
            coords.rename(
                columns={
                    "airport": "destination_airport",
                    "lat": "destination_lat",
                    "lon": "destination_lon",
                }
            ),
            on="destination_airport",
            how="left",
        )

    airport_subset = ["lat", "lon"] if {"lat", "lon"}.issubset(airports.columns) else []
    route_subset = (
        ["origin_lat", "origin_lon", "destination_lat", "destination_lon"]
        if {"origin_lat", "origin_lon", "destination_lat", "destination_lon"}.issubset(
            routes.columns
        )
        else []
    )
    return airports.dropna(subset=airport_subset, how="any"), routes.dropna(
        subset=route_subset, how="any"
    )


def robust_frontier_layers(results_folder: str) -> pd.DataFrame:
    if not results_folder:
        return pd.DataFrame()
    base = RESULTS_ROOT / results_folder
    frames = [
        _csv(base / "aviation_robust_frontier.csv"),
        _csv(base / "maritime_robust_frontier.csv"),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    frontier = pd.concat(frames, ignore_index=True)
    for column in ("year", "expected_utility", "robust_score", "candidate_utility"):
        if column in frontier.columns:
            frontier[column] = pd.to_numeric(frontier[column], errors="coerce")
    if "selected_flag" in frontier.columns:
        frontier["selected_flag"] = (
            frontier["selected_flag"].astype(str).str.lower().isin({"true", "1", "yes"})
        )
    return frontier


def _scenario_family(folder: str) -> str:
    return SCENARIO_SUFFIX_PATTERN.sub("", folder)


def _scenario_name(folder: str) -> str:
    match = SCENARIO_SUFFIX_PATTERN.search(folder)
    return match.group(1) if match else folder


def scenario_sibling_folders(folder: str) -> list[str]:
    """Every results folder that is the same run as `folder` under a different
    scenario. A folder with no scenario suffix is its own only sibling."""
    if not SCENARIO_SUFFIX_PATTERN.search(folder):
        return [folder] if folder else []
    family = _scenario_family(folder)
    return [
        candidate
        for candidate in list_result_folders()
        if SCENARIO_SUFFIX_PATTERN.search(candidate) and _scenario_family(candidate) == family
    ]


@functools.lru_cache(maxsize=256)
def _metric_year_totals(folder: str, metric: str) -> pd.Series:
    """Year totals for one run and metric.

    Cached because `use_memo` keeps only the current (family, metric) result,
    so toggling metrics back and forth would otherwise re-read every sibling's
    aircraft.csv each time. Callers build new frames from the result rather
    than mutating it. Results on disk are static for the life of the process.
    """
    path = RESULTS_ROOT / folder / "aircraft.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    columns = TRAJECTORY_METRIC_SOURCES.get(metric)
    try:
        if metric == "trips":
            frame = pd.read_csv(path, usecols=["year"])
            return frame.groupby("year").size().astype(float)
        if columns is None:
            return pd.Series(dtype=float)
        frame = pd.read_csv(path, usecols=["year", *columns])
    except Exception:
        return pd.Series(dtype=float)

    total = None
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        total = values if total is None else total + values
    frame = frame.assign(_value=total)
    return frame.groupby("year")["_value"].sum()


@functools.lru_cache(maxsize=128)
def electricity_fuel_energy(folder: str) -> pd.DataFrame:
    """Fuel energy (kWh) per year and electricity-derived carrier for one run.

    Deliberately stops at the *fuel* energy rather than the electricity: the
    conversion efficiencies are user-adjustable, and keeping them out of the
    cached step means changing one re-scales the result without re-reading any
    CSV.
    """
    path = RESULTS_ROOT / folder / "aircraft.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year", "source", "fuel_kwh"])

    columns = ["year", "primary_energy_carrier", "secondary_energy_carrier"]
    columns += ["primary_energy_consumption", "secondary_energy_consumption"]
    try:
        frame = pd.read_csv(path, usecols=lambda column: column in columns)
    except Exception:
        return pd.DataFrame(columns=["year", "source", "fuel_kwh"])
    if "year" not in frame.columns:
        return pd.DataFrame(columns=["year", "source", "fuel_kwh"])

    rows = []
    for source, spec in ELECTRICITY_SOURCES.items():
        carrier_column = spec["carrier_column"]
        field = spec["field"]
        if carrier_column not in frame.columns or field not in frame.columns:
            continue
        match_value = spec.get("match_value", source)
        matched = frame.loc[
            frame[carrier_column].astype(str).str.strip().str.lower().eq(match_value)
        ]
        if matched.empty:
            continue
        totals = (
            pd.to_numeric(matched[field], errors="coerce")
            .fillna(0.0)
            .groupby(matched["year"])
            .sum()
        )
        totals = totals.loc[totals > 0]
        if totals.empty:
            continue
        rows.append(
            pd.DataFrame(
                {
                    "year": totals.index.astype(int),
                    "fuel_kwh": totals.to_numpy(dtype=float),
                    "source": source,
                }
            )
        )
    if not rows:
        return pd.DataFrame(columns=["year", "source", "fuel_kwh"])
    return pd.concat(rows, ignore_index=True)


def electricity_demand(folder: str, efficiencies: dict[str, float]) -> pd.DataFrame:
    """Electricity (kWh) needed per year and source to make that run's fuels."""
    fuel = electricity_fuel_energy(folder)
    if fuel.empty:
        return pd.DataFrame(columns=["year", "source", "electricity_kwh"])
    frame = fuel.copy()
    frame["efficiency"] = (
        frame["source"]
        .map(lambda source: efficiencies.get(source, ELECTRICITY_SOURCES[source]["efficiency"]))
        .astype(float)
        .clip(lower=0.01)
    )
    frame["electricity_kwh"] = frame["fuel_kwh"] / frame["efficiency"]
    return frame[["year", "source", "electricity_kwh", "fuel_kwh"]]


def electricity_trajectories(folder: str, efficiencies: dict[str, float]) -> pd.DataFrame:
    """Total electricity demand per year for every sibling scenario."""
    frames = []
    for sibling in scenario_sibling_folders(folder):
        demand = electricity_demand(sibling, efficiencies)
        if demand.empty:
            continue
        totals = demand.groupby("year", as_index=False)["electricity_kwh"].sum()
        totals = totals.rename(columns={"electricity_kwh": "value"})
        totals["scenario"] = _scenario_name(sibling)
        frames.append(totals)
    if not frames:
        return pd.DataFrame(columns=["year", "value", "scenario"])
    return pd.concat(frames, ignore_index=True)


def scenario_trajectories(folder: str, metric: str) -> pd.DataFrame:
    """Per-year totals of `metric` for every sibling scenario of `folder`,
    as a long frame of year/scenario/value."""
    frames = []
    for sibling in scenario_sibling_folders(folder):
        totals = _metric_year_totals(sibling, metric)
        if totals.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "year": totals.index.astype(int),
                    "value": totals.to_numpy(dtype=float),
                    "scenario": _scenario_name(sibling),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=["year", "value", "scenario"])
    return pd.concat(frames, ignore_index=True)


def collapse_identical_trajectories(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Scenarios whose trajectories are numerically identical are drawn as one
    line, labelled with how many they stand for.

    Eight lines where six sit exactly on top of each other would show the
    reader a single visible line and hide that five more are underneath it --
    the collapse says so explicitly instead. Returns the frame with a `series`
    column plus the membership behind each label.
    """
    if frame.empty:
        return frame.assign(series=pd.Series(dtype=str)), {}

    signatures: dict[tuple, list[str]] = {}
    for scenario, group in frame.groupby("scenario"):
        ordered = group.sort_values("year")
        signature = tuple(ordered["value"].round(6).tolist())
        signatures.setdefault(signature, []).append(str(scenario))

    label_for_scenario: dict[str, str] = {}
    membership: dict[str, list[str]] = {}
    for members in signatures.values():
        members = sorted(members)
        label = members[0] if len(members) == 1 else f"{members[0]} +{len(members) - 1} more"
        membership[label] = members
        for member in members:
            label_for_scenario[member] = label

    labelled = frame.copy()
    labelled["series"] = labelled["scenario"].astype(str).map(label_for_scenario)
    # Keep one row per series/year. The collapsed members hold identical values,
    # so the extra rows would draw redundant coincident line marks -- and, worse,
    # Vega-Lite's pivot sums rows sharing a label, which silently multiplied the
    # hover tooltip by the group size (a 5-scenario group read 5x its real value).
    labelled = labelled.drop_duplicates(subset=["series", "year"], keep="first")
    labelled = labelled.reset_index(drop=True)
    return labelled, membership


def _display_scale(max_abs: float, metric: str) -> tuple[float, str]:
    metadata = METRIC_METADATA.get(metric, {})
    large_factor = metadata.get("large_factor")
    large_unit = metadata.get("large_unit")
    threshold = metadata.get("large_threshold", LARGE_METRIC_THRESHOLD)
    if large_factor and large_unit and max_abs >= threshold:
        return float(large_factor), str(large_unit)
    return 1.0, str(metadata.get("unit", ""))


def _show_table(frame: pd.DataFrame, max_rows: int = 12) -> None:
    if frame.empty:
        solara.Markdown("_No rows available._")
        return
    display = frame.head(max_rows).copy()
    for column in display.columns:
        if pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].round(4)
    table_html = display.to_html(index=False, escape=True, classes="natm-table")
    solara.HTML(
        tag="div",
        unsafe_innerHTML=(
            "<style>"
            ".natm-table{border-collapse:collapse;width:100%;font-size:0.88rem;}"
            ".natm-table th,.natm-table td{border:1px solid #ddd;padding:6px 8px;}"
            ".natm-table th{background:#f5f5f5;text-align:left;}"
            "</style>"
            f"{table_html}"
        ),
    )


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records"))


def _metric_label(metric: str) -> str:
    return METRIC_METADATA.get(metric, {"label": metric.replace("_", " ").title()})["label"]


def _metric_unit_options(metric: str) -> list[str]:
    metadata = METRIC_METADATA.get(metric, {})
    base_unit = metadata.get("unit", "")
    large_unit = metadata.get("large_unit", "")
    options = [AUTO_UNIT_OPTION]
    if base_unit:
        options.append(base_unit)
    if large_unit and large_unit not in options:
        options.append(large_unit)
    return options if len(options) > 1 else []


def hub_ranking(
    airports: pd.DataFrame,
    year: int | None,
    carrier: str,
    metric: str,
) -> pd.DataFrame:
    """Per-hub totals of `metric` for the selected year/carrier, ranked.

    Filtered the same way as the map layer, so the bars and the bubbles are
    always showing the same slice of data.
    """
    if airports.empty or "airport" not in airports.columns:
        return pd.DataFrame(columns=["airport", "value"])
    column = metric if metric in airports.columns else None
    if column is None:
        return pd.DataFrame(columns=["airport", "value"])

    frame = airports
    if year is not None and "year" in frame.columns:
        frame = frame.loc[frame["year"].eq(year)]
    if carrier != "all" and "carrier" in frame.columns:
        frame = frame.loc[frame["carrier"].astype(str).str.lower().eq(carrier)]
    if frame.empty:
        return pd.DataFrame(columns=["airport", "value"])

    ranked = (
        frame.groupby("airport", as_index=False)[column]
        .sum()
        .rename(columns={column: "value"})
        .sort_values("value", ascending=False)
    )
    return ranked.loc[ranked["value"] > 0].reset_index(drop=True)


def hub_ranking_chart(frame: pd.DataFrame, metric: str) -> alt.LayerChart | None:
    """Ranked bars for hub magnitude.

    A bubble encodes magnitude as area, which cannot carry this data: the
    busiest port is ~450x the smallest, so a bubble scale that keeps the small
    ports visible makes the biggest one swallow half the coastline, and area is
    the encoding people read least accurately anyway. Length on a shared
    baseline handles the range and stays readable, with the value written next
    to each bar so nothing depends on judging a size by eye.
    """
    if frame.empty:
        return None

    factor, unit = _display_scale(float(frame["value"].abs().max()), metric)
    plot = frame.assign(value=frame["value"] / factor)
    order = plot["airport"].tolist()
    axis_title = _metric_label(metric) + (f" ({unit})" if unit else "")

    base = alt.Chart(plot).encode(
        y=alt.Y("airport:N", title=None, sort=order, axis=alt.Axis(labelFontSize=11)),
        x=alt.X("value:Q", title=axis_title, axis=alt.Axis(grid=True, tickCount=4)),
    )
    # A single measure, so one hue for every bar -- shading them by size would
    # re-encode the length the bar already shows.
    bars = base.mark_bar(color=CATEGORICAL_PALETTE[0], height=alt.RelativeBandSize(0.7))
    # Precision from the magnitude actually on screen: whole numbers once the
    # values are in the hundreds, decimals only when they would otherwise all
    # collapse to 0.
    largest = float(plot["value"].abs().max())
    value_format = ",.0f" if largest >= 100 else (",.2f" if largest >= 1 else ",.3f")
    labels = base.mark_text(
        align="left", dx=4, fontSize=10, color=CHART_INK_SECONDARY
    ).encode(text=alt.Text("value:Q", format=value_format))

    return (
        alt.layer(bars, labels)
        .properties(
            width="container",
            height=alt.Step(20),
            padding={"right": 90, "top": 5, "bottom": 5, "left": 5},
        )
        .configure_view(stroke=None, fill=CHART_SURFACE)
        .configure_axis(
            gridColor=CHART_GRID,
            domainColor=CHART_AXIS,
            tickColor=CHART_AXIS,
            labelColor=CHART_INK_MUTED,
            titleColor=CHART_INK_SECONDARY,
            titleFontSize=11,
            titleFontWeight="normal",
        )
    )


def trajectory_chart(frame: pd.DataFrame, metric: str) -> alt.LayerChart | None:
    """Multi-series line chart of a metric over time, one line per distinct
    scenario trajectory."""
    if frame.empty or "series" not in frame.columns:
        return None

    factor, unit = _display_scale(float(frame["value"].abs().max()), metric)
    plot = frame.assign(value=frame["value"] / factor)
    series_names = sorted(plot["series"].unique())
    axis_title = _metric_label(metric) + (f" ({unit})" if unit else "")

    color = alt.Color(
        "series:N",
        title=None,
        scale=alt.Scale(domain=series_names, range=list(CATEGORICAL_PALETTE[: len(series_names)])),
        legend=(
            None
            if len(series_names) < 2
            else alt.Legend(
                orient="bottom", direction="vertical", labelLimit=420, symbolStrokeWidth=3
            )
        ),
    )
    x = alt.X(
        "year:Q",
        title=None,
        scale=alt.Scale(nice=False, zero=False),
        axis=alt.Axis(format="d", tickCount=6, grid=False),
    )
    y = alt.Y("value:Q", title=axis_title, axis=alt.Axis(grid=True, tickCount=5))

    base = alt.Chart(plot)
    # Linear, not a smoothed spline: these are discrete annual values, and
    # curve interpolation would invent between-year movement that the model
    # never produced (fleet turnover lands on specific years).
    lines = base.mark_line(strokeWidth=2).encode(x=x, y=y, color=color)

    # Crosshair + one tooltip listing every series at the hovered year, so
    # values are readable without landing on a specific 2px line.
    hover = alt.selection_point(
        fields=["year"], nearest=True, on="pointerover", empty=False, clear="pointerout"
    )
    crosshair = (
        base.transform_pivot("series", value="value", groupby=["year"])
        .mark_rule(color=CHART_INK_MUTED, strokeWidth=1)
        .encode(
            x=x,
            opacity=alt.condition(hover, alt.value(0.45), alt.value(0)),
            tooltip=[alt.Tooltip("year:Q", title="Year", format="d")]
            + [alt.Tooltip(f"{name}:Q", title=name, format=",.1f") for name in series_names],
        )
        .add_params(hover)
    )
    markers = lines.mark_point(size=70, filled=True).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0))
    )

    layers = [lines, crosshair, markers]
    # <= 4 series are direct-labelled at the line end as well as in the legend,
    # so identity never rests on colour alone.
    if len(series_names) <= 4:
        final_year = plot["year"].max()
        layers.append(
            alt.Chart(plot.loc[plot["year"].eq(final_year)])
            .mark_text(align="left", dx=8, fontSize=11, fontWeight="bold")
            .encode(x=x, y=y, text="series:N", color=color)
        )

    return (
        alt.layer(*layers)
        .properties(
            width="container",
            height=300,
            padding={"right": 150, "top": 5, "bottom": 5, "left": 5},
        )
        .configure_view(stroke=None, fill=CHART_SURFACE)
        .configure_axis(
            gridColor=CHART_GRID,
            gridWidth=1,
            domainColor=CHART_AXIS,
            tickColor=CHART_AXIS,
            labelColor=CHART_INK_MUTED,
            titleColor=CHART_INK_SECONDARY,
            labelFontSize=11,
            titleFontSize=11,
            titleFontWeight="normal",
        )
        .configure_legend(labelColor=CHART_INK_SECONDARY, labelFontSize=11, symbolType="stroke")
    )


def _deck_map_payload(
    airports: pd.DataFrame,
    routes: pd.DataFrame,
    year: int | None,
    carrier: str,
    metric: str,
    unit_overrides: dict[str, str] | None = None,
    fit_key: str = "",
) -> dict:
    """Filter the map layers for the current selection and return a plain,
    JSON-safe dict to post into the already-mounted map iframe (see
    `_MAP_SHELL_HTML` / `CartographicMap`). Filtering/carrier-breakdown logic
    lives here so the front end only ever receives ready-to-draw data; the
    front end itself never re-fetches or reloads for a filter change.
    """
    if year is not None:
        if "year" in airports.columns:
            airports = airports.loc[airports["year"].eq(year)]
        if "year" in routes.columns:
            routes = routes.loc[routes["year"].eq(year)]

    point_col = (
        metric
        if metric in airports.columns
        else (
            "fuel_demand"
            if "fuel_demand" in airports.columns
            else ("trips" if "trips" in airports.columns else "co2")
        )
    )

    # Build a per-airport breakdown of point_col across every carrier present
    # (from the year-filtered but not yet carrier-filtered rows), so a hovered
    # bubble can show every carrier's value side by side -- the carrier toggle
    # above still controls which bubble is drawn/sized, but the tooltip no
    # longer requires flipping tabs to compare carriers.
    breakdown_lookup: dict[str, dict[str, float]] = {}
    if "carrier" in airports.columns and "airport" in airports.columns:
        for airport_code, group in airports.groupby("airport"):
            breakdown_lookup[airport_code] = {
                str(row["carrier"]): float(row[point_col])
                for _, row in group.iterrows()
                if point_col in row and pd.notna(row[point_col])
            }

    if carrier != "all":
        if "carrier" in airports.columns:
            airports = airports.loc[airports["carrier"].astype(str).str.lower().eq(carrier)]
        if "carrier" in routes.columns:
            routes = routes.loc[routes["carrier"].astype(str).str.lower().eq(carrier)]

    if breakdown_lookup and "airport" in airports.columns:
        airports = airports.copy()
        airports["carrier_breakdown"] = airports["airport"].map(
            lambda code: json.dumps(breakdown_lookup.get(code, {})),
        )
    line_col = (
        metric
        if metric in routes.columns
        else ("energy_demand" if "energy_demand" in routes.columns else "trips")
    )
    unit_overrides = unit_overrides or {}

    # One arc per origin-destination pair. The route summary is broken down by
    # aircraft type, so a single city pair arrives as a dozen rows -- drawn raw
    # that stacks a dozen coincident arcs, each sized by its own slice of the
    # metric rather than the route's total.
    route_keys = [
        column
        for column in (
            "origin_airport",
            "destination_airport",
            "origin_lat",
            "origin_lon",
            "destination_lat",
            "destination_lon",
            # Sea-lane geometry (maritime only); grouped on rather than
            # aggregated, so the path survives to the front end intact.
            "path",
        )
        if column in routes.columns
    ]
    route_values = [
        column
        for column in dict.fromkeys([line_col, "trips", "co2", "fuel_demand"])
        if column in routes.columns and pd.api.types.is_numeric_dtype(routes[column])
    ]
    if route_keys and route_values:
        routes = routes.groupby(route_keys, as_index=False)[route_values].sum()
    elif route_keys:
        routes = routes[route_keys].drop_duplicates()

    # The front end draws a zero-width (invisible) arc for a route with no
    # value on the active metric -- e.g. routes out of airports the model has
    # no fleet based at. Dropping them keeps the payload to what is actually
    # rendered instead of shipping thousands of invisible arcs.
    if line_col in routes.columns and pd.api.types.is_numeric_dtype(routes[line_col]):
        routes = routes.loc[routes[line_col].fillna(0.0) > 0]

    # Ship only the fields the map reads. The rest of the summary (aircraft
    # type, per-km intensities, ...) is never touched by the front end and
    # would multiply the payload pushed on every filter change.
    airport_columns = [
        column
        for column in dict.fromkeys(
            ["airport", "lat", "lon", "carrier_breakdown", point_col, "fuel_demand", "trips", "co2"]
        )
        if column in airports.columns
    ]
    if airport_columns:
        airports = airports[airport_columns]

    return {
        "airports": _records(airports.round(6)),
        "routes": _records(routes.round(6)),
        "pointMetric": point_col,
        "lineMetric": line_col,
        "unitOverrides": unit_overrides,
        # Identifies the dataset, so the map reframes when the folder changes
        # but holds the camera steady for metric/year/carrier changes.
        "fitKey": fit_key,
    }


def _build_map_shell_html() -> str:
    """Static map page: loads maplibre-gl/deck.gl and initializes an empty
    map once, then waits for `postMessage({airports, routes, pointMetric,
    lineMetric, unitOverrides})` from the parent page to (re)draw layers.

    This never embeds scenario data, so it never needs to change/reload when
    the selected folder, year, carrier, or metric changes -- only the
    `postMessage` payload does. That's what lets the iframe stay mounted
    (see `CartographicMap` / cartographic_map.vue) instead of being torn
    down and rebuilt -- with a fresh WebGL context and basemap refetch from
    cartocdn -- on every filter interaction, which is what made the map feel
    slow to use.
    """
    metric_metadata = METRIC_METADATA
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet">
  <style>
    html, body, #map {{ margin: 0; width: 100%; height: 100%; overflow: hidden; }}
    body {{ font-family: Arial, sans-serif; background: #fff; }}
    .deck-tooltip {{ font-size: 12px; line-height: 1.35; }}
  </style>
  <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
  <script src="https://unpkg.com/deck.gl@9.0.35/dist.min.js"></script>
</head>
<body>
  <div id="map"></div>
  <script>
    let airports = [];
    let routes = [];
    let pointMetric = null;
    let lineMetric = null;
    const metricMetadata = {json.dumps(metric_metadata)};
    let unitOverrides = {{}};
    const {{DeckGL, ScatterplotLayer, ArcLayer, PathLayer}} = deck;
    const value = (row, key) => Number(row[key] ?? 0);
    const metricLabel = (key) => metricMetadata[key]?.label ?? key;
    const metricUnit = (key) => metricMetadata[key]?.unit ?? "";
    const formatValue = (rawValue, key) => {{
      const metadata = metricMetadata[key] ?? {{}};
      const unitOverride = unitOverrides[key];
      const useLargeUnit = unitOverride
        ? unitOverride === metadata.large_unit
        : Math.abs(rawValue) >= (metadata.large_threshold ?? {LARGE_METRIC_THRESHOLD})
          && metadata.large_unit
          && metadata.large_factor;
      const displayValue = useLargeUnit ? rawValue / metadata.large_factor : rawValue;
      const unit = unitOverride || (useLargeUnit ? metadata.large_unit : metricUnit(key));
      const number = displayValue.toLocaleString(undefined, {{ maximumFractionDigits: 2 }});
      return unit ? `${{number}} ${{unit}}` : number;
    }};
    const formatMetric = (row, key) => formatValue(value(row, key), key);
    const hasMetric = (row, key) => Object.prototype.hasOwnProperty.call(row, key);
    const positiveValues = (rows, key) => rows
      .map(row => value(row, key))
      .filter(value => value > 0);
    const scale = (row, key, maxValue) => Math.sqrt(Math.max(value(row, key), 0) / maxValue);
    const tooltip = (info) => {{
      const row = info.object;
      if (!row) return null;
      if (row.airport) {{
        const lines = [
          `<strong>${{row.airport}}</strong>`,
          `${{metricLabel(pointMetric)}}: ${{formatMetric(row, pointMetric)}}`
        ];
        if (pointMetric !== "fuel_demand" && hasMetric(row, "fuel_demand")) {{
          lines.push(`Fuel demand: ${{formatMetric(row, "fuel_demand")}}`);
        }}
        if (pointMetric !== "trips" && hasMetric(row, "trips")) {{
          lines.push(`Trips: ${{formatMetric(row, "trips")}}`);
        }}
        if (pointMetric !== "co2" && hasMetric(row, "co2")) {{
          lines.push(`CO2 emissions: ${{formatMetric(row, "co2")}}`);
        }}
        if (row.carrier_breakdown) {{
          try {{
            const breakdown = JSON.parse(row.carrier_breakdown);
            const entries = Object.entries(breakdown).filter(([, v]) => v > 0);
            if (entries.length >= 1) {{
              lines.push(`<em>${{metricLabel(pointMetric)}} by carrier:</em>`);
              entries
                .sort((a, b) => b[1] - a[1])
                .forEach(([carrierName, carrierValue]) => {{
                  lines.push(
                    `&nbsp;&nbsp;${{carrierName}}: ${{formatValue(carrierValue, pointMetric)}}`
                  );
                }});
            }}
          }} catch (e) {{ /* malformed breakdown, skip */ }}
        }}
        return {{
          html: lines.join("<br>")
        }};
      }}
      const lines = [
        `<strong>${{row.origin_airport}} -> ${{row.destination_airport}}</strong>`,
        `${{metricLabel(lineMetric)}}: ${{formatMetric(row, lineMetric)}}`
      ];
      if (lineMetric !== "trips" && hasMetric(row, "trips")) {{
        lines.push(`Trips: ${{formatMetric(row, "trips")}}`);
      }}
      if (lineMetric !== "co2" && hasMetric(row, "co2")) {{
        lines.push(`CO2 emissions: ${{formatMetric(row, "co2")}}`);
      }}
      return {{
        html: lines.join("<br>")
      }};
    }};

    let deckInstance = null;

    // Frame whatever the first payload actually contains: the aviation network
    // spans Vancouver to East Asia, while a maritime run is a cluster of German
    // ports -- one hardcoded view cannot suit both. Only applied on first
    // render, so later filter changes leave the camera where the user put it.
    function fittedViewState() {{
      const lons = [];
      const lats = [];
      const push = (lon, lat) => {{
        if (Number.isFinite(lon) && Number.isFinite(lat)) {{ lons.push(lon); lats.push(lat); }}
      }};
      airports.forEach(d => push(Number(d.lon), Number(d.lat)));
      routes.forEach(d => {{
        push(Number(d.origin_lon), Number(d.origin_lat));
        push(Number(d.destination_lon), Number(d.destination_lat));
      }});
      if (!lons.length || !deck.WebMercatorViewport) return null;
      const minMax = (arr) => arr.reduce(
        (acc, v) => [Math.min(acc[0], v), Math.max(acc[1], v)],
        [Infinity, -Infinity]
      );
      const [minLon, maxLon] = minMax(lons);
      const [minLat, maxLat] = minMax(lats);
      if (minLon === maxLon && minLat === maxLat) return null;
      try {{
        const viewport = new deck.WebMercatorViewport({{
          width: window.innerWidth || 800,
          height: window.innerHeight || 600
        }});
        const fitted = viewport.fitBounds([[minLon, minLat], [maxLon, maxLat]], {{ padding: 60 }});
        return {{
          latitude: fitted.latitude,
          longitude: fitted.longitude,
          zoom: Math.min(fitted.zoom, 9),
          pitch: 25,
          bearing: 0
        }};
      }} catch (e) {{
        return null;
      }}
    }}

    // Sea-lane geometry arrives as a JSON string per route; parsed once per
    // payload rather than on every deck.gl accessor call.
    const pathCache = new Map();
    function parsePath(raw) {{
      if (!raw) return [];
      if (Array.isArray(raw)) return raw;
      if (pathCache.has(raw)) return pathCache.get(raw);
      let parsed = [];
      try {{ parsed = JSON.parse(raw) || []; }} catch (e) {{ parsed = []; }}
      pathCache.set(raw, parsed);
      return parsed;
    }}

    function buildLayers() {{
      const airportMax = Math.max(1, ...positiveValues(airports, pointMetric));
      const routeMax = Math.max(1, ...positiveValues(routes, lineMetric));
      const hasPaths = routes.length > 0 && routes[0].path != null;
      return [
        new ScatterplotLayer({{
          id: "airports",
          data: airports,
          getPosition: d => [d.lon, d.lat],
          // Sized in screen pixels within a capped range, not in metres. A
          // metre radius scaled to the busiest hub covered ~80km of coastline
          // and hid every neighbour behind it (and grew without limit as you
          // zoomed out). Magnitude is compared properly in the ranked bars
          // below the map; here the size is only a hint, and location is the
          // job the map actually does.
          getRadius: d => value(d, pointMetric) > 0
            ? 4 + scale(d, pointMetric, airportMax) * 14
            : 3.5,
          radiusUnits: "pixels",
          getFillColor: [38, 120, 255, 150],
          getLineColor: [11, 54, 112, 230],
          lineWidthMinPixels: 1,
          stroked: true,
          pickable: true
        }}),
        // Sea lanes carry real geometry and are drawn as paths that follow the
        // water; flights have no such constraint and stay as great-circle arcs.
        // Distinct ids per layer type: deck.gl matches layers by id across
        // updates, so reusing one id when switching an arc network for a path
        // network makes it carry the old layer's state into the new type and
        // fail to build geometry ("Cannot read properties of undefined
        // (reading 'updateGeometry')"), leaving the previous frame on screen.
        hasPaths
          ? new PathLayer({{
              id: "routes-path",
              data: routes,
              getPath: d => parsePath(d.path),
              getWidth: d => value(d, lineMetric) > 0
                ? 1.5 + scale(d, lineMetric, routeMax) * 5
                : 0,
              widthUnits: "pixels",
              widthMinPixels: 1,
              getColor: [0, 110, 180, 190],
              capRounded: true,
              jointRounded: true,
              pickable: true
            }})
          : new ArcLayer({{
              id: "routes-arc",
              data: routes,
              getSourcePosition: d => [d.origin_lon, d.origin_lat],
              getTargetPosition: d => [d.destination_lon, d.destination_lat],
              getWidth: d => value(d, lineMetric) > 0
                ? 1 + scale(d, lineMetric, routeMax) * 5
                : 0,
              getSourceColor: [255, 120, 40, 200],
              getTargetColor: [40, 180, 150, 200],
              pickable: true
            }})
      ];
    }}

    let fitKey = null;
    let pendingFitKey = null;
    function render() {{
      if (deckInstance && pendingFitKey !== fitKey) {{
        // A different results folder: its data can sit somewhere else entirely
        // (a global flight network vs a cluster of German ports), so reframe.
        // Metric/year/carrier changes keep the same fitKey and leave the
        // camera exactly where the user left it.
        fitKey = pendingFitKey;
        const view = fittedViewState();
        if (view) deckInstance.setProps({{ initialViewState: view }});
      }}
      if (!deckInstance) {{
        fitKey = pendingFitKey;
        deckInstance = new DeckGL({{
          container: "map",
          mapStyle: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
          initialViewState: fittedViewState()
            || {{ latitude: 46, longitude: 10, zoom: 2.6, pitch: 25, bearing: 0 }},
          controller: true,
          getTooltip: tooltip,
          layers: buildLayers()
        }});
      }} else {{
        deckInstance.setProps({{ layers: buildLayers() }});
      }}
    }}

    window.addEventListener("message", (event) => {{
      const payload = event.data;
      if (!payload || typeof payload !== "object") return;
      airports = payload.airports || [];
      routes = payload.routes || [];
      pointMetric = payload.pointMetric;
      lineMetric = payload.lineMetric;
      unitOverrides = payload.unitOverrides || {{}};
      pendingFitKey = payload.fitKey ?? null;
      render();
    }});
  </script>
</body>
</html>"""


_MAP_SHELL_HTML = _build_map_shell_html()


@solara.component_vue("cartographic_map.vue")
def CartographicMap(shell_html: str, map_data: dict): ...


def _electricity_panel(
    collapsed: tuple[pd.DataFrame, dict[str, list[str]]],
    fuel_by_source: pd.DataFrame,
    efficiency_state: dict,
    efficiencies: dict[str, float],
    folder: str,
) -> None:
    """Electricity needed to make this run's electricity-derived fuels."""
    trajectories, membership = collapsed
    present = (
        sorted(fuel_by_source["source"].unique().tolist()) if not fuel_by_source.empty else []
    )

    solara.Markdown("### Electricity demand")
    if not present:
        solara.Markdown(
            "This case uses no electricity-derived energy carrier "
            "(no e-fuel, hydrogen or direct electricity), so it needs no electricity. "
            "The maritime cases run on LNG, marine diesel and biofuel; "
            "aviation cases pick up e-kerosene as the SAF mandate tightens."
        )
        return

    solara.Markdown(
        "Electricity required *upstream* to produce the fuels burned -- not energy burned "
        "in flight. The model has no conversion-efficiency parameter, so the figures below "
        "rest on the assumptions set here and scale directly with them."
    )
    for source in present:
        spec = ELECTRICITY_SOURCES[source]
        state = efficiency_state[source]
        solara.SliderFloat(
            label=f"{spec['label']} efficiency ({spec['note']})",
            value=state,
            min=0.10,
            max=1.0,
            step=0.01,
        )
        solara.Markdown(
            f"&nbsp;&nbsp;`{state.value:.2f}` -> "
            f"**{1.0 / max(state.value, 0.01):.2f} kWh electricity per kWh of fuel**"
        )

    chart = trajectory_chart(trajectories, "electricity_demand")
    if chart is None:
        return

    scenario_count = sum(len(members) for members in membership.values())
    solara.Markdown(f"#### Electricity demand over time, all {scenario_count} scenario runs")
    solara.FigureAltair(chart)

    identical = {label: members for label, members in membership.items() if len(members) > 1}
    if identical:
        merged = "; ".join(
            f"**{label}** = {', '.join(members)}" for label, members in sorted(identical.items())
        )
        solara.Markdown(
            f"Scenarios drawn as one line because their values are identical: {merged}."
        )

    # The year x scenario grid.
    factor, unit = _display_scale(float(trajectories["value"].abs().max()), "electricity_demand")
    table = (
        trajectories.assign(value=trajectories["value"] / factor)
        .pivot_table(index="year", columns="series", values="value", aggfunc="first")
        .reset_index()
    )
    table = table.loc[table["year"].mod(5).eq(0) | table["year"].eq(table["year"].max())]
    table.columns.name = None
    value_columns = [column for column in table.columns if column != "year"]
    table[value_columns] = table[value_columns].round(3)
    table = table.rename(
        columns={
            "year": "Year",
            **{c: f"{c}{f' ({unit})' if unit else ''}" for c in value_columns},
        }
    )
    _show_table(table, max_rows=12)

    # Which carrier the demand comes from, for the selected run.
    breakdown = electricity_demand(folder, efficiencies)
    if not breakdown.empty:
        # Year x fuel-type grid: which technology's electricity need this is
        # (e-kerosene, hydrogen, hybrid-assist battery, ...), not just the
        # combined total the chart/table above show.
        by_year_source = (
            breakdown.assign(
                label=breakdown["source"].map(lambda s: ELECTRICITY_SOURCES[s]["label"]),
                value=breakdown["electricity_kwh"] / factor,
            )
            .pivot_table(index="year", columns="label", values="value", aggfunc="sum")
            .reset_index()
        )
        last_year = by_year_source["year"].max()
        by_year_source = by_year_source.loc[
            by_year_source["year"].mod(5).eq(0) | by_year_source["year"].eq(last_year)
        ]
        by_year_source.columns.name = None
        fuel_columns = [c for c in by_year_source.columns if c != "year"]
        by_year_source[fuel_columns] = by_year_source[fuel_columns].fillna(0.0).round(3)
        by_year_source = by_year_source.rename(
            columns={"year": "Year", **{c: f"{c} ({unit})" for c in fuel_columns}}
        )
        solara.Markdown(f"#### Electricity demand by fuel type -- `{_scenario_name(folder)}`")
        _show_table(by_year_source, max_rows=12)

        by_source = breakdown.groupby("source", as_index=False)[
            ["electricity_kwh", "fuel_kwh"]
        ].sum()
        by_source["Carrier"] = by_source["source"].map(
            lambda s: ELECTRICITY_SOURCES[s]["label"]
        )
        by_source[f"Electricity over horizon ({unit})"] = (
            by_source["electricity_kwh"] / factor
        ).round(3)
        by_source[f"Fuel energy produced ({unit})"] = (by_source["fuel_kwh"] / factor).round(3)
        solara.Markdown(
            f"#### Where the electricity goes (total over horizon) -- `{_scenario_name(folder)}`"
        )
        _show_table(
            by_source[
                [
                    "Carrier",
                    f"Electricity over horizon ({unit})",
                    f"Fuel energy produced ({unit})",
                ]
            ],
            max_rows=8,
        )


@solara.component
def Page() -> None:
    folders = list_result_folders()
    selected = solara.use_reactive(folders[0] if folders else "")
    # Reading/merging the per-scenario CSVs (aircraft.csv, route summaries, ...)
    # only depends on the selected results folder, but Page() re-renders on
    # every year/carrier/metric interaction too. Without memoizing on
    # selected.value, each slider drag or toggle click re-read and
    # reprocessed the CSVs from scratch before the map could update.
    airports, routes = solara.use_memo(
        lambda: build_map_ready_layers(selected.value), [selected.value]
    )
    # Hooks must run unconditionally on every render (Page() has an early
    # `return` below when there's no map data), so this is computed here
    # rather than next to where it's used further down.
    robust_frontier = solara.use_memo(
        lambda: robust_frontier_layers(selected.value), [selected.value]
    )
    years = sorted(
        {
            int(y)
            for y in pd.concat(
                [
                    airports.get("year", pd.Series(dtype=float)),
                    routes.get("year", pd.Series(dtype=float)),
                ],
                ignore_index=True,
            )
            .dropna()
            .tolist()
        }
    )
    year_value = solara.use_reactive(years[-1] if years else None)
    if years and year_value.value not in years:
        year_value.value = years[-1]
    carriers = sorted(
        set(airports.get("carrier", pd.Series(["all"])).dropna().astype(str).str.lower().tolist())
        | set(routes.get("carrier", pd.Series(["all"])).dropna().astype(str).str.lower().tolist())
        | {"all"}
    )
    carrier = solara.use_reactive("all")
    if carrier.value not in carriers:
        carrier.value = "all"
    metric_options = [
        column
        for column in (
            "fuel_uplift_mwh",
            "fuel_demand",
            "energy_demand",
            "fuel_uplift_kg",
            "trips",
            "co2",
            "h2o",
            "nox",
            "co",
            "hc",
            "soot",
            "sox",
        )
        if column in airports.columns or column in routes.columns
    ] or ["energy_demand"]
    metric = solara.use_reactive(metric_options[0])
    if metric.value not in metric_options:
        metric.value = metric_options[0]
    display_unit = solara.use_reactive(AUTO_UNIT_OPTION)
    # Conversion efficiencies for the electricity panel. Reactive state has to
    # be created on every render (hooks rule), so these live up here with the
    # other reactives rather than beside the panel that uses them.
    efficiency_state = {
        source: solara.use_reactive(spec["efficiency"])
        for source, spec in ELECTRICITY_SOURCES.items()
    }
    efficiencies = {source: float(state.value) for source, state in efficiency_state.items()}
    electricity_by_scenario = solara.use_memo(
        lambda: collapse_identical_trajectories(
            electricity_trajectories(selected.value, efficiencies)
        ),
        [_scenario_family(selected.value), tuple(sorted(efficiencies.items()))],
    )
    electricity_sources_present = solara.use_memo(
        lambda: electricity_fuel_energy(selected.value),
        [selected.value],
    )
    # Computed here, above the early return below, because hooks must run on
    # every render in the same order. Keyed on the scenario family rather than
    # the folder, so switching between siblings reuses the same trajectories.
    trajectories, trajectory_membership = solara.use_memo(
        lambda: collapse_identical_trajectories(
            scenario_trajectories(selected.value, metric.value)
        ),
        [_scenario_family(selected.value), metric.value],
    )

    solara.Title("NATM Cartographic Dashboard")
    solara.Markdown(
        "Browser-native NATM map using Solara + deck.gl. Use filters for scenario/year/carrier "
        "to compare transition patterns and adoption hotspots."
    )

    if folders:
        solara.Select(label="Results folder", values=folders, value=selected)
    else:
        solara.Markdown(
            "No saved simulation results found; showing processed aviation fallback data."
        )

    if airports.empty and routes.empty:
        solara.Warning("No map-ready airport/route data found in this results folder.")
        return

    if years:
        solara.Markdown(
            f"Selected year: `{year_value.value}`. Available years: `{years[0]}`-`{years[-1]}`."
        )
        solara.SliderInt("Year", value=year_value, min=years[0], max=years[-1])

    solara.ToggleButtonsSingle(value=carrier, values=carriers)

    metric_label_to_key = {_metric_label(option): option for option in metric_options}
    metric_labels = list(metric_label_to_key)
    active_metric_label = _metric_label(metric.value)

    def set_metric_label(label: str) -> None:
        metric.value = metric_label_to_key.get(label, metric_options[0])
        display_unit.value = AUTO_UNIT_OPTION

    solara.ToggleButtonsSingle(
        value=active_metric_label,
        values=metric_labels,
        on_value=set_metric_label,
    )
    selected_metric_metadata = METRIC_METADATA.get(
        metric.value,
        {"label": metric.value, "unit": ""},
    )
    selected_metric_label = selected_metric_metadata["label"]
    selected_metric_unit = selected_metric_metadata["unit"]
    selected_large_unit = selected_metric_metadata.get("large_unit")
    unit_options = _metric_unit_options(metric.value)
    if unit_options and display_unit.value not in unit_options:
        display_unit.value = AUTO_UNIT_OPTION
    if len(unit_options) > 2:
        solara.ToggleButtonsSingle(value=display_unit, values=unit_options)
    if selected_metric_unit:
        if display_unit.value != AUTO_UNIT_OPTION:
            unit_text = display_unit.value
        else:
            unit_text = (
                f"{selected_metric_unit}; large values shown as {selected_large_unit}"
                if selected_large_unit
                else selected_metric_unit
            )
        solara.Markdown(f"Selected metric: `{selected_metric_label}` (`{unit_text}`).")
    else:
        solara.Markdown(f"Selected metric: `{selected_metric_label}`.")

    unit_overrides = (
        {metric.value: display_unit.value} if display_unit.value != AUTO_UNIT_OPTION else {}
    )
    # `shell_html` never changes (it embeds no scenario data), so the iframe
    # stays mounted across every year/carrier/metric/folder change; only
    # `map_data` (a small JSON payload) updates, pushed into the already-live
    # map via postMessage instead of a full document reload -- see
    # cartographic_map.vue. That avoids re-fetching the basemap tiles/style/
    # fonts and re-initializing WebGL on every interaction, which is what
    # made the map feel slow to use.
    map_data = _deck_map_payload(
        airports,
        routes,
        year_value.value,
        carrier.value,
        metric.value,
        unit_overrides,
        fit_key=selected.value,
    )
    # A constant key, independent of any filter state: the optional unit
    # toggle rendered just above (`if len(unit_options) > 2`) appears or
    # disappears depending on which metric is selected, which would
    # otherwise shift this component's position among its siblings and make
    # Reacton treat it as a new element -- remounting the iframe -- purely
    # because a sibling was added or removed, not because the map itself
    # needed to change.
    CartographicMap(shell_html=_MAP_SHELL_HTML, map_data=map_data).key("cartographic-map")

    ranking = hub_ranking(airports, year_value.value, carrier.value, metric.value)
    ranking_chart = hub_ranking_chart(ranking, metric.value)
    if ranking_chart is not None:
        leader = ranking.iloc[0]
        share = leader["value"] / ranking["value"].sum() * 100 if ranking["value"].sum() else 0.0
        solara.Markdown(
            f"### {_metric_label(metric.value)} by hub, {year_value.value}"
            f"\n\n`{leader['airport']}` is {share:.0f}% of the {len(ranking)} hubs shown. "
            "Bar length is comparable in a way bubble area is not."
        )
        solara.FigureAltair(ranking_chart)

    chart = trajectory_chart(trajectories, metric.value)
    if chart is not None:
        scenario_count = sum(len(members) for members in trajectory_membership.values())
        solara.Markdown(
            f"### {_metric_label(metric.value)} over time"
            f"\n\nAll {scenario_count} scenario runs of this case, every year of the horizon "
            "-- the map above shows a single year of a single run."
        )
        solara.FigureAltair(chart)

        identical = {
            label: members for label, members in trajectory_membership.items() if len(members) > 1
        }
        if identical:
            merged = "; ".join(
                f"**{label}** = {', '.join(members)}"
                for label, members in sorted(identical.items())
            )
            solara.Markdown(
                "Scenarios with numerically identical trajectories are drawn as "
                f"one line: {merged}."
            )

        # Table view: the readable twin of the chart. Three of the eight series
        # hues sit below 3:1 against the chart surface, so the values have to be
        # reachable as text, not by colour matching alone.
        factor, unit = _display_scale(float(trajectories["value"].abs().max()), metric.value)
        table = (
            trajectories.assign(value=trajectories["value"] / factor)
            .pivot_table(index="year", columns="series", values="value", aggfunc="first")
            .reset_index()
        )
        table = table.loc[table["year"].mod(5).eq(0) | table["year"].eq(table["year"].max())]
        table.columns.name = None  # drop the pivot axis name, else it renders as a stray header
        value_columns = [column for column in table.columns if column != "year"]
        table[value_columns] = table[value_columns].round(0)
        table = table.rename(
            columns={
                "year": "Year",
                **{c: f"{c}{f' ({unit})' if unit else ''}" for c in value_columns},
            }
        )
        _show_table(table, max_rows=12)

    _electricity_panel(
        electricity_by_scenario,
        electricity_sources_present,
        efficiency_state,
        efficiencies,
        selected.value,
    )

    if not robust_frontier.empty:
        if year_value.value is not None and "year" in robust_frontier.columns:
            robust_frontier = robust_frontier.loc[robust_frontier["year"].eq(year_value.value)]
        selected_rows = robust_frontier.loc[
            robust_frontier.get("selected_flag", pd.Series(False, index=robust_frontier.index))
        ].copy()
        if not selected_rows.empty:
            summary = (
                selected_rows.drop_duplicates(
                    subset=[
                        column
                        for column in (
                            "year",
                            "sector_name",
                            "application_name",
                            "operator_name",
                            "asset_id",
                            "segment",
                            "decision_attitude",
                            "selected_technology",
                        )
                        if column in selected_rows.columns
                    ],
                )
                .groupby(
                    [
                        "sector_name",
                        "application_name",
                        "decision_attitude",
                        "selected_technology",
                    ],
                    as_index=False,
                )
                .agg(
                    selected_count=("selected_technology", "size"),
                    expected_utility=("expected_utility", "mean"),
                    robust_score=("robust_score", "mean"),
                )
                .sort_values(["sector_name", "application_name", "selected_count"])
            )
            solara.Markdown("### Robust Frontier Selection Summary")
            _show_table(summary, max_rows=16)


_LAUNCH_SENTINEL = "NATM_DASHBOARD_LAUNCHED"

if __name__ == "__main__" and os.environ.get(_LAUNCH_SENTINEL) != "1":
    # Solara apps are normally launched via the `solara run` CLI rather than
    # plain `python`, since the dashboard needs the Solara dev server (not
    # just a script execution). Re-exec through that CLI so
    # `python cartographic_dashboard.py` (optionally with e.g. --port 8765)
    # works as a direct entry point too.
    #
    # Solara's own app loader also execs this file with __name__ forced to
    # "__main__" (to support scripts that call solara.run(...) themselves),
    # so without the sentinel env var this block would trigger again inside
    # the very server it just launched, recursing into `solara run` forever.
    import subprocess
    import sys

    raise SystemExit(
        subprocess.run(
            [sys.executable, "-m", "solara", "run", __file__, *sys.argv[1:]],
            check=False,
            env={**os.environ, _LAUNCH_SENTINEL: "1"},
        ).returncode
    )
