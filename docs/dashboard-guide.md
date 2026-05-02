# NATM Dashboard Guide

This document explains how to use the Solara/Mesa dashboards included in
`dashboard_examples/`.

## 1. What The Dashboards Are For

NATM dashboards support two ways of exploring model behavior:

1. `Live case`
   The dashboard instantiates the Mesa model directly from a case folder under
   `data/` and reruns the simulation inside the dashboard session.

2. `Saved results`
   The dashboard reads previously generated CSV outputs from a folder under
   `simulation_results/` and visualizes those results without rerunning the
   model.

This gives NATM both:

- a live exploratory dashboard
- a saved-run results dashboard

using the same Solara-based interface.

## 2. Install Dashboard Dependencies

From the repository root:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dashboard]
```

If you see a Starlette startup error mentioning `on_startup`, repair the
environment with:

```powershell
python -m pip install "starlette<1" "solara-server[starlette]>=1.40"
```

## 3. Available Dashboard Files

### Aviation passenger

```powershell
solara run dashboard_examples/aviation_passenger_baseline_dashboard.py
```

### Aviation cargo

```powershell
solara run dashboard_examples/aviation_cargo_baseline_dashboard.py
```

### Maritime cargo

```powershell
solara run dashboard_examples/maritime_cargo_baseline_dashboard.py
```

### Maritime passenger

```powershell
solara run dashboard_examples/maritime_passenger_baseline_dashboard.py
```

### Cartographic (deck.gl)

```powershell
solara run dashboard_examples/cartographic_dashboard.py
```

If the `solara` command is not recognized, use:

```powershell
python -m solara run dashboard_examples/aviation_passenger_baseline_dashboard.py
```

and replace the file path with the dashboard you want.

## 4. How To Use Live Case Mode

When the dashboard opens in the browser, look for the `Dashboard Source` card.

Choose:

- `Live case`

In this mode, the dashboard:

- resolves the case configured in the dashboard file
- instantiates the Mesa model
- reruns the simulation inside the dashboard
- shows live model summary and detailed charts

The live mode uses the case folder name that is hard-coded in the dashboard
file, for example:

- `baseline-transition`
- `baseline-cargo-transition`
- `baseline-maritime-cargo-transition`
- `baseline-maritime-passenger-transition`

## 5. How To Use Saved Results Mode

If you already generated outputs using `run.py` or the CLI, and those outputs
exist under:

```text
simulation_results/<your-run-name>/
```

then you can visualize them without rerunning the model.

Steps:

1. Launch the dashboard for the application you want.
2. In the browser, open the `Dashboard Source` card.
3. Switch from `Live case` to `Saved results`.
4. Choose your results folder from the `Results folder` dropdown.

The dashboard will then read the saved CSV files from that folder.

The standalone cartographic dashboard also reads folders under
`simulation_results/`, but it does not use the `Dashboard Source` live/saved
toggle. It always visualizes saved result folders when present, and falls back
to processed aviation sample data when no saved results exist.

## 6. What A Results Folder Must Contain

For a results folder to appear in the saved-results dropdown, it must contain:

- `model_summary.csv`
- `agents.csv`
- and the application-compatible sector files

For aviation dashboards:

- `aviation_technology.csv`
- `aviation_energy_emissions.csv`
- `aviation_investments.csv`

For maritime dashboards:

- `maritime_technology.csv`
- `maritime_energy_emissions.csv`
- `maritime_investments.csv`

## 7. What The Dashboards Show

The current dashboards provide:

- latest run snapshot
- alternative share over time
- transition pressure over time
- policy support over time
- operator-level alternative shares
- technology mix by year
- energy by carrier
- investments by operator
- operator drill-down cards
- report-ready summary tables
- aviation preprocessing and OpenAP output explorer
- aviation flight-route network
- aviation airport fuel-demand map

Important note on energy units:

- the model stores raw energy internally in `kWh`
- the dashboard converts displayed energy values to `TWh`

## 8. Aviation Preprocessing And OpenAP Views

For aviation dashboards, extra cards are shown when files exist under:

```text
data/processed/aviation/
```

These cards use outputs from the aviation preprocessing pipeline, especially:

- `aviation_fleet_stock_enriched.csv`
- `aviation_stock_matching_report.csv`
- `aviation_activity_profiles.csv`
- `aviation_airport_allocation.csv`
- `openap_flight_fuel_emissions.csv`
- `openap_aircraft_type_summary.csv`
- `openap_route_summary.csv`
- `openap_aircraft_type_mapping_log.csv`

The `Aviation Preprocessing Explorer` summarizes stock matching, activity
profiles, airport allocation, OpenAP aircraft type mapping, and OpenAP fuel and
emissions totals.

The `Flight Route Network` shows a schematic airport network. It is useful for
seeing which routes dominate by trips, fuel, energy, or CO2, but it is not a
geographic map.

The `Airport Fuel Demand Map` uses airport coordinates from the aviation
preprocessing `airport_metadata` path in `scenario.yaml`. It draws the airports
and route lines on a lightweight Europe basemap, so it is geographically
anchored rather than a pure network graph. Airport bubbles show demand
associated with each airport, and route lines show the selected route metric. By
default, airport demand is assigned to departing airports, which is the better
first proxy for airport fuel demand. The map can also switch to
`Origin + destination activity` if you want an activity-footprint view.

## 9. Typical Workflow

### Generate a saved run

```powershell
python run.py
```

This writes a run folder into:

```text
simulation_results/<selected_example>/
```

### Open the matching dashboard

```powershell
solara run dashboard_examples/aviation_passenger_baseline_dashboard.py
```

For the standalone cartographic map:

```powershell
solara run dashboard_examples/cartographic_dashboard.py
```

### Switch to saved results

In the browser:

- `Dashboard Source` -> `Saved results`
- choose the run folder from the dropdown

## 10. Current Design

All four dashboard entrypoints use the shared helper:

- `dashboard_examples/common_case_dashboard.py`

This file provides:

- common live/saved-results switching
- shared chart structure
- shared results-folder loading
- shared formatting for energy and investment charts

## 11. Cartographic Dashboard Architecture

`dashboard_examples/cartographic_dashboard.py` provides a browser-native
cartographic dashboard with Solara + deck.gl (no QGIS Desktop required).

Pipeline:

`NATM simulation output -> map-ready layer builder -> Solara controls -> deck.gl map`

### Data Sources And Year Handling

When a selected result folder contains `aircraft.csv`, the cartographic
dashboard uses that file as the primary simulation source. It aggregates
aircraft-level records by year, hub airport, and energy carrier, so the year
slider follows the simulated years in the run, for example `2025`-`2030`.

The generated airport bubbles use:

- `main_hub_base` / `main_hub` for airport placement
- `primary_energy_carrier` for carrier filtering
- `primary_energy_consumption + secondary_energy_consumption` for `energy_demand`
- `total_emission` for `co2`
- aircraft counts for `trips`

Route arcs need geographic endpoints. If the result folder does not provide a
dedicated route-flow file, the dashboard reuses route geometry from:

```text
data/processed/aviation/openap_route_summary.csv
```

Those OpenAP route endpoints are treated as geometry only in that case; the
visible route width is scaled from the selected simulated year and hub totals.
This allows a multi-year simulation run to use baseline/preprocessing route
geometry while still showing year-specific simulated demand intensity.

### Optional Map-Ready Files

For fully route-specific cartographic output, place these optional files into a
result folder:

- `airport_fuel_demand.csv` with airport coordinates and demand metrics
- `route_energy_flow.csv` with route-level endpoints and flow metrics

When those files are present, they can provide direct map-ready airport and
route layers. When they are missing, the dashboard falls back to the simulation
`aircraft.csv` aggregation and processed aviation route geometry described
above.

### Controls And Rendering

Key capabilities:

- clickable airports and route/corridor arcs
- hover tooltips for airport and route metrics
- year slider for simulated-year playback
- result-folder switching
- carrier filtering (`kerosene`, `saf`, `hydrogen`, `electricity`, `ammonia` when present)
- metric switching (`energy_demand`, `trips`, `co2`)

The map is rendered as deck.gl JavaScript inside an iframe. This avoids the
Jupyter-widget rendering path that can cause blank Solara pages in a normal
browser session. The browser must be able to load deck.gl, MapLibre, and the
CARTO basemap assets from their public CDNs.

Visual widths and bubble radii are normalized per selected year so large
simulated energy or emissions values do not turn arcs into filled color bands.
