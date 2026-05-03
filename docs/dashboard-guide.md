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

### Common case dashboard

```powershell
solara run dashboard_examples/common_case_dashboard.py
```

Use the `Live case` selector in the browser to choose aviation passenger,
aviation cargo, maritime cargo, or maritime passenger cases.

### Cartographic (deck.gl)

```powershell
solara run dashboard_examples/cartographic_dashboard.py
```

If the `solara` command is not recognized, use:

```powershell
python -m solara run dashboard_examples/common_case_dashboard.py
```

and use the browser controls to choose the case you want.

## 4. How To Use Live Case Mode

When the dashboard opens in the browser, look for the `Dashboard Source` card.

Choose:

- `Live case`

In this mode, the dashboard:

- resolves the case selected in the `Case` card
- instantiates the Mesa model
- reruns the simulation inside the dashboard
- shows live model summary and detailed charts

The live case selector lists dashboard-compatible folders under `data/`, for
example:

- `baseline-passenger-transition`
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

1. Launch the common case dashboard.
2. Choose the matching case in the `Case` card.
3. Open the `Dashboard Source` card.
4. Switch from `Live case` to `Saved results`.
5. Choose your results folder from the `Results folder` dropdown.

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
- `aviation_robust_frontier.csv` if ambiguity-aware decisions were enabled

For maritime dashboards:

- `maritime_technology.csv`
- `maritime_energy_emissions.csv`
- `maritime_investments.csv`
- `maritime_robust_frontier.csv` if ambiguity-aware decisions were enabled

## 7. What The Dashboards Show

The current dashboards provide:

- latest run snapshot
- alternative share over time
- transition pressure over time
- policy support over time
- operator-level alternative shares
- technology mix by year
- energy by carrier
- emissions by pollutant
- investments by operator
- robust frontier candidate scores when robust frontier outputs exist
- operator drill-down cards
- report-ready summary tables
- aviation preprocessing and OpenAP output explorer
- aviation flight-route network
- aviation airport fuel-demand map

Important note on energy units:

- the model stores raw energy internally in `kWh`
- the dashboard converts displayed energy values to `TWh`

Important note on emissions and mass units:

- simulation emissions and OpenAP pollutant totals are displayed in `tonnes`
- cartographic CO2 and non-CO2 pollutant metrics are converted from `kg` to
  `tonnes` when displayed as large values
- cartographic fuel uplift mass is converted from `kg` to `tonnes` when
  displayed as a large value
- cartographic MWh-based metrics switch to `TWh` once the displayed value is at
  least `1,000 MWh`

When `aviation_robust_frontier.csv` or `maritime_robust_frontier.csv` exists,
the standard dashboard adds a `Robust Frontier` panel. It lets you filter by
year, operator, segment, `decision_attitude`, and aircraft/vessel. The main
frontier chart compares candidate technologies as labeled points using
worst-case mean utility on the x-axis and worst-case expected-shortfall utility
on the y-axis, and highlights the selected technology. The panel also keeps the
candidate utility summary and selected-technology shares by year and attitude
so `risk_neutral` and `risk_averse` behavior can be compared directly.

The cartographic dashboard keeps the map as the main view and adds a compact
robust frontier selection summary below the map when robust frontier outputs are
present in the selected results folder.

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
profiles, airport allocation, OpenAP aircraft type mapping, OpenAP fuel totals,
and OpenAP pollutant totals. When OpenAP pollutant columns exist, the explorer
shows a pollutant table instead of only a CO2 line. Supported pollutant columns
include `co2_kg`, `h2o_kg`, `nox_kg`, `co_kg`, `hc_kg`, `soot_kg`, and
`sox_kg`.

The shared dashboard also includes an `Emissions` panel. It detects available
emissions columns and shows:

- simulation emissions, such as `total_emission` and `chargeable_emission`
- OpenAP pollutants, such as `co2_kg`, `h2o_kg`, `nox_kg`, `co_kg`, `hc_kg`,
  `soot_kg`, and `sox_kg`
- a year selector
- a pollutant selector
- a pollutant totals chart in tonnes
- a breakdown table by operator, route, origin, or technology depending on the
  columns available in the selected source

The `Flight Route Network` shows a schematic airport network. It is useful for
seeing which routes dominate by trips, fuel, energy, or CO2, but it is not a
geographic map.

The `Airport Fuel Demand Map` uses airport coordinates from the aviation
preprocessing `airport_metadata` path in `scenario.yaml`. It draws the airports
and route lines on a lightweight Europe basemap, so it is geographically
anchored rather than a pure network graph. Airport bubbles show demand
associated with each airport, and route lines show the selected route metric.
When postprocessed `airport_fuel_demand.csv` and `route_energy_flow.csv` files
exist in the selected results folder, the map uses those allocation outputs
first. Otherwise, it falls back to OpenAP route summaries. In fallback mode,
airport demand is assigned to departing airports by default, and the map can
also switch to `Origin + destination activity` if you want an
activity-footprint view.

## 9. Typical Workflow

### Generate a saved run

```powershell
python run.py
```

This writes a run folder into:

```text
simulation_results/<selected_example>/
```

### Open the common case dashboard

```powershell
solara run dashboard_examples/common_case_dashboard.py
```

For the standalone cartographic map:

```powershell
solara run dashboard_examples/cartographic_dashboard.py
```

To generate dedicated map-ready fuel allocation files before opening the map:

```powershell
natm-airport-fuel-allocation --results simulation_results/<selected_example>
```

If the new console command is not recognized before reinstalling the editable
package, use:

```powershell
python -m navaero_transition_model.postprocessing.airport_fuel_allocation_cli --results simulation_results/<selected_example>
```

### Switch to saved results

In the browser:

- `Dashboard Source` -> `Saved results`
- choose the run folder from the dropdown

## 10. Current Design

The standard live/saved-results dashboard is maintained as one script:

- `dashboard_examples/common_case_dashboard.py`

This file provides:

- live case selection across aviation passenger, aviation cargo, maritime cargo,
  and maritime passenger cases
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

When a selected result folder contains postprocessed `airport_fuel_demand.csv`
and `route_energy_flow.csv` files, the cartographic dashboard uses those files
as the primary map-ready sources. When those files are missing and the selected
result folder contains `aircraft.csv`, the dashboard aggregates aircraft-level
records by year, hub airport, and energy carrier, so the year slider follows
the simulated years in the run, for example `2025`-`2030`.

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

These files can be generated after a simulation run with:

```powershell
natm-airport-fuel-allocation --results simulation_results/<your-run-name>
```

or:

```powershell
python -m navaero_transition_model.postprocessing.airport_fuel_allocation_cli --results simulation_results/<your-run-name>
```

The allocation command is a postprocessor. It first tries to use
flightlist/OpenAP aircraft sequences to estimate uplift at the departure airport
for each next trip. When exact aircraft identifiers are not available in both
the simulation output and flightlist data, it falls back to synthetic allocation
from simulated aircraft energy, hub airports, and processed route shares.

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
- metric switching for available fields, including `fuel_uplift_mwh`,
  `fuel_demand`, `energy_demand`, `fuel_uplift_kg`, `trips`, `co2`, `h2o`,
  `nox`, `co`, `hc`, `soot`, and `sox`
- metric labels and units in tooltips
- human-readable metric buttons instead of raw CSV column names
- a display-unit toggle for convertible metrics, such as showing
  `fuel_uplift_kg` as either `kg` or `tonnes`
- adaptive display units:
  - MWh-based metrics switch to `TWh` at `1,000 MWh`
  - fuel uplift mass switches from `kg` to `tonnes` for large values
  - CO2 and other pollutant metrics switch from `kg` to `tonnes` for large
    values

The map is rendered as deck.gl JavaScript inside an iframe. This avoids the
Jupyter-widget rendering path that can cause blank Solara pages in a normal
browser session. The browser must be able to load deck.gl, MapLibre, and the
CARTO basemap assets from their public CDNs.

Visual widths and bubble radii are normalized per selected year so large
simulated energy or emissions values do not turn arcs into filled color bands.
