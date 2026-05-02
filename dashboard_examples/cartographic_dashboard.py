from __future__ import annotations

import json
from pathlib import Path

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
RESULTS_ROOT = ROOT / "simulation_results"
AIRPORT_METADATA_PATH = ROOT / "data" / "examples" / "aviation_preprocessing" / "airports_sample.csv"
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


def _airport_coordinates() -> pd.DataFrame:
    airports = _csv(AIRPORT_METADATA_PATH)
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
        }
    )
    if not {"airport", "lat", "lon"}.issubset(airports.columns):
        return pd.DataFrame(columns=["airport", "lat", "lon"])

    airports["lat"] = pd.to_numeric(airports["lat"], errors="coerce")
    airports["lon"] = pd.to_numeric(airports["lon"], errors="coerce")
    return (
        pd.concat([airports[["airport", "lat", "lon"]], EXTRA_AIRPORT_COORDS], ignore_index=True)
        .dropna()
        .drop_duplicates("airport")
    )


def _hub_to_airport(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return HUB_AIRPORT_ALIASES.get(text.lower(), text.upper())


def _simulated_airport_layers(base: Path, coords: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    aircraft = _csv(base / "aircraft.csv")
    if aircraft.empty or "year" not in aircraft.columns:
        return pd.DataFrame(), pd.DataFrame()

    hub_col = "main_hub_base" if "main_hub_base" in aircraft.columns else "main_hub"
    if hub_col not in aircraft.columns:
        return pd.DataFrame(), pd.DataFrame()

    aircraft = aircraft.copy()
    aircraft["airport"] = aircraft[hub_col].map(_hub_to_airport)
    aircraft["carrier"] = aircraft.get("primary_energy_carrier", pd.Series("all", index=aircraft.index)).fillna("all").astype(str).str.lower()
    aircraft["energy_demand"] = pd.to_numeric(
        aircraft.get("primary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
        errors="coerce",
    ).fillna(0.0) + pd.to_numeric(
        aircraft.get("secondary_energy_consumption", pd.Series(0.0, index=aircraft.index)),
        errors="coerce",
    ).fillna(0.0)
    aircraft["co2"] = pd.to_numeric(aircraft.get("total_emission", pd.Series(0.0, index=aircraft.index)), errors="coerce").fillna(0.0)

    airports = (
        aircraft.groupby(["year", "airport", "carrier"], as_index=False)
        .agg(
            energy_demand=("energy_demand", "sum"),
            co2=("co2", "sum"),
            trips=("airport", "size"),
        )
        .merge(coords, on="airport", how="left")
    )

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
    outgoing_counts = routes.groupby(["year", "origin_airport"], as_index=False).size().rename(columns={"size": "outgoing_routes"})
    routes = routes.merge(
        origin_totals.rename(columns={"airport": "origin_airport"}),
        on=["year", "origin_airport"],
        how="left",
    ).merge(outgoing_counts, on=["year", "origin_airport"], how="left")
    routes["outgoing_routes"] = pd.to_numeric(routes["outgoing_routes"], errors="coerce").fillna(1.0).clip(lower=1.0)
    for col in ("energy_demand", "co2", "trips"):
        routes[col] = pd.to_numeric(routes[col], errors="coerce").fillna(0.0) / routes["outgoing_routes"]

    return airports, routes


def build_map_ready_layers(results_folder: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = RESULTS_ROOT / results_folder
    coords = _airport_coordinates()
    airports, routes = _simulated_airport_layers(base, coords)

    if airports.empty:
        airports = _csv(base / "airport_fuel_demand.csv")
    if routes.empty:
        routes = _csv(base / "route_energy_flow.csv")

    if airports.empty:
        openap_airports = _csv(ROOT / "data" / "processed" / "aviation" / "aviation_airport_allocation.csv")
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

    if not airports.empty and {"airport"}.issubset(airports.columns) and not {"lat", "lon"}.issubset(airports.columns):
        airports = airports.merge(coords, on="airport", how="left")

    if routes.empty:
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
                }
            )

    for col in ("lat", "lon", "fuel_demand", "co2", "year"):
        if col in airports.columns:
            airports[col] = pd.to_numeric(airports[col], errors="coerce")

    for col in ("origin_lat", "origin_lon", "destination_lat", "destination_lon", "energy_demand", "trips", "co2", "year"):
        if col in routes.columns:
            routes[col] = pd.to_numeric(routes[col], errors="coerce")

    if {"origin_airport", "destination_airport"}.issubset(routes.columns) and {"airport", "lat", "lon"}.issubset(airports.columns):
        coords = pd.concat([coords, airports[["airport", "lat", "lon"]]], ignore_index=True).dropna().drop_duplicates("airport")
        routes = routes.merge(coords.rename(columns={"airport": "origin_airport", "lat": "origin_lat", "lon": "origin_lon"}), on="origin_airport", how="left")
        routes = routes.merge(coords.rename(columns={"airport": "destination_airport", "lat": "destination_lat", "lon": "destination_lon"}), on="destination_airport", how="left")

    airport_subset = ["lat", "lon"] if {"lat", "lon"}.issubset(airports.columns) else []
    route_subset = (
        ["origin_lat", "origin_lon", "destination_lat", "destination_lon"]
        if {"origin_lat", "origin_lon", "destination_lat", "destination_lon"}.issubset(routes.columns)
        else []
    )
    return airports.dropna(subset=airport_subset, how="any"), routes.dropna(subset=route_subset, how="any")


def _json_records(frame: pd.DataFrame) -> str:
    payload = json.loads(frame.to_json(orient="records"))
    return json.dumps(payload).replace("</", "<\\/")


def _deck_map_html(airports: pd.DataFrame, routes: pd.DataFrame, year: int | None, carrier: str, metric: str) -> str:
    if year is not None:
        if "year" in airports.columns:
            airports = airports.loc[airports["year"].eq(year)]
        if "year" in routes.columns:
            routes = routes.loc[routes["year"].eq(year)]

    if carrier != "all":
        if "carrier" in airports.columns:
            airports = airports.loc[airports["carrier"].astype(str).str.lower().eq(carrier)]
        if "carrier" in routes.columns:
            routes = routes.loc[routes["carrier"].astype(str).str.lower().eq(carrier)]

    point_col = metric if metric in airports.columns else ("fuel_demand" if "fuel_demand" in airports.columns else ("trips" if "trips" in airports.columns else "co2"))
    line_col = metric if metric in routes.columns else ("energy_demand" if "energy_demand" in routes.columns else "trips")

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
    const airports = {_json_records(airports)};
    const routes = {_json_records(routes)};
    const pointMetric = {json.dumps(point_col)};
    const lineMetric = {json.dumps(line_col)};
    const {{DeckGL, ScatterplotLayer, ArcLayer}} = deck;
    const value = (row, key) => Number(row[key] ?? 0);
    const positiveValues = (rows, key) => rows.map(row => value(row, key)).filter(value => value > 0);
    const airportMax = Math.max(1, ...positiveValues(airports, pointMetric));
    const routeMax = Math.max(1, ...positiveValues(routes, lineMetric));
    const scale = (row, key, maxValue) => Math.sqrt(Math.max(value(row, key), 0) / maxValue);
    const tooltip = (info) => {{
      const row = info.object;
      if (!row) return null;
      if (row.airport) {{
        return {{
          html: `<strong>${{row.airport}}</strong><br>Fuel demand: ${{value(row, "fuel_demand").toLocaleString()}}<br>Trips: ${{value(row, "trips").toLocaleString()}}<br>CO2: ${{value(row, "co2").toLocaleString()}}`
        }};
      }}
      return {{
        html: `<strong>${{row.origin_airport}} -> ${{row.destination_airport}}</strong><br>${{lineMetric}}: ${{value(row, lineMetric).toLocaleString()}}<br>Trips: ${{value(row, "trips").toLocaleString()}}<br>CO2: ${{value(row, "co2").toLocaleString()}}`
      }};
    }};

    new DeckGL({{
      container: "map",
      mapStyle: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
      initialViewState: {{ latitude: 50, longitude: 8, zoom: 3.6, pitch: 25, bearing: 0 }},
      controller: true,
      getTooltip: tooltip,
      layers: [
        new ScatterplotLayer({{
          id: "airports",
          data: airports,
          getPosition: d => [d.lon, d.lat],
          getRadius: d => value(d, pointMetric) > 0 ? 10000 + scale(d, pointMetric, airportMax) * 42000 : 7000,
          getFillColor: [38, 120, 255, 165],
          getLineColor: [11, 54, 112, 220],
          lineWidthMinPixels: 1,
          pickable: true
        }}),
        new ArcLayer({{
          id: "routes",
          data: routes,
          getSourcePosition: d => [d.origin_lon, d.origin_lat],
          getTargetPosition: d => [d.destination_lon, d.destination_lat],
          getWidth: d => value(d, lineMetric) > 0 ? 1 + scale(d, lineMetric, routeMax) * 5 : 0,
          getSourceColor: [255, 120, 40, 200],
          getTargetColor: [40, 180, 150, 200],
          pickable: true
        }})
      ]
    }});
  </script>
</body>
</html>"""


@solara.component
def Page() -> None:
    folders = list_result_folders()
    selected = solara.use_reactive(folders[0] if folders else "")
    airports, routes = build_map_ready_layers(selected.value)
    years = sorted(
        {
            int(y)
            for y in pd.concat([airports.get("year", pd.Series(dtype=float)), routes.get("year", pd.Series(dtype=float))], ignore_index=True).dropna().tolist()
        }
    )
    year_value = solara.use_reactive(years[-1] if years else None)
    carriers = sorted(
        set(airports.get("carrier", pd.Series(["all"])).dropna().astype(str).str.lower().tolist())
        | set(routes.get("carrier", pd.Series(["all"])).dropna().astype(str).str.lower().tolist())
        | {"all"}
    )
    carrier = solara.use_reactive("all")
    metric = solara.use_reactive("energy_demand")

    solara.Title("NATM Cartographic Dashboard")
    solara.Markdown(
        "Browser-native NATM map using Solara + deck.gl. Use filters for scenario/year/carrier "
        "to compare transition patterns and adoption hotspots."
    )

    if folders:
        solara.Select(label="Results folder", values=folders, value=selected)
    else:
        solara.Markdown("No saved simulation results found; showing processed aviation fallback data.")

    if airports.empty and routes.empty:
        solara.Warning("No map-ready airport/route data found in this results folder.")
        return

    if years:
        solara.Markdown(f"Selected year: `{year_value.value}`. Available years: `{years[0]}`-`{years[-1]}`.")
        solara.SliderInt("Year", value=year_value, min=years[0], max=years[-1])

    solara.ToggleButtonsSingle(value=carrier, values=carriers)

    solara.ToggleButtonsSingle(value=metric, values=["energy_demand", "trips", "co2"])

    map_html = _deck_map_html(airports, routes, year_value.value, carrier.value, metric.value)
    solara.HTML(
        tag="iframe",
        attributes={
            "srcdoc": map_html,
            "title": "NATM cartographic map",
        },
        style={"width": "100%", "height": "720px", "border": "0"},
    )
