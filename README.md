# NATM

NATM stands for NavAero Transition Model.

NATM is a technology transition diffusion model for aviation and maritime
transport systems. It is designed to simulate how operators adopt new aircraft,
vessels, fuels, and related technologies over time under changing policy,
cost, infrastructure, and operational conditions.

The model is built as a Mesa-based agent-based simulation with explicit agents,
case data, decision-logic plugins, fleet management, environment state, and
structured outputs. The goal is to provide a cleaner and more maintainable
architecture than the earlier Melodie-based implementation, while still
capturing the business and policy dynamics behind technology diffusion.

In practical terms, NATM is intended to help explore questions such as:

- how quickly alternative technologies diffuse across operators
- how policy and fuel prices affect investment decisions
- how much fuel demand shifts by energy carrier over time
- how emissions and investment costs evolve during the transition

The current repository includes working aviation-passenger, aviation-cargo,
maritime-cargo, and maritime-passenger test cases, while the architecture is
designed to extend further into additional transport applications as the model
grows.

## Installation

NATM requires Python `3.11` or newer.

### First-Time Setup (PowerShell)

```powershell
git clone https://github.com/Manish-Khanra/NATM.git
cd NATM
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

If your default `python` does not point to Python `3.11+`, use a specific
interpreter such as:

```powershell
py -3.11 -m venv .venv
```

## Quick Start

### Run The Model

```powershell
.venv\Scripts\Activate.ps1
python run.py
```

That launcher writes the results automatically into:

```text
simulation_results/<selected_example>/
```

including `model_summary.csv`, the detailed CSV tables, and `natm_runs.sqlite`.

If you want to run a case directly through the CLI instead:

```powershell
natm --case baseline-transition --output simulation_results/baseline.csv
```

To export the richer Mesa result tables as well:

```powershell
natm --case baseline-transition --output simulation_results/baseline.csv --details-dir simulation_results/baseline-details
```

To persist both case inputs and run outputs into SQLite:

```powershell
natm --case baseline-transition --output simulation_results/baseline.csv --details-dir simulation_results/baseline-details --sqlite-db simulation_results/natm_runs.sqlite
```

### Pre-Commit Setup

Install the hooks once per clone:

```powershell
.venv\Scripts\Activate.ps1
pre-commit install
```

Run them manually across the whole repository:

```powershell
pre-commit run --all-files
```

### Aviation Preprocessing Workflow

NATM now also includes a dedicated aviation data-ingestion and preprocessing
layer for building data-grounded baseline aviation inputs from:

- fleet stock tables
- OpenSky aircraft metadata
- OpenSky / Zenodo monthly flight lists
- airport metadata
- Germany calibration targets

The preprocessing code is separate from the simulation core and lives in:

```text
navaero_transition_model/aviation_preprocessing/
```

Typical processed outputs are written to:

```text
data/processed/aviation/
```

You can run the preprocessing CLI with a synthetic example like this:

```powershell
.venv\Scripts\Activate.ps1
natm-aviation-preprocess `
  --stock-input data\baseline-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-transition\aviation_technology_catalog.csv `
  --calibration-input data\examples\aviation_preprocessing\germany_calibration_input.csv
```

OpenAP fuel and emissions estimation is optional because it adds an extra
flight-performance dependency. Install it only when you want to turn
OpenSky/Zenodo flight lists into baseline fuel and emissions intensities:

```powershell
python -m pip install -e .[openap]
```

Then add the OpenAP flag to the preprocessing command:

```powershell
natm-aviation-preprocess `
  --stock-input data\baseline-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-transition\aviation_technology_catalog.csv `
  --calibration-input data\examples\aviation_preprocessing\germany_calibration_input.csv `
  --estimate-openap-fuel `
  --openap-mode synthetic
```

This writes OpenAP flight, aircraft-type, route, mapping-log, and validation
outputs into `data/processed/aviation/` and enriches
`aviation_activity_profiles.csv` for the core Mesa simulation.

You can also run the scenario-defined preprocessing flow from `run.py`. The
baseline passenger case stores its preprocessing recipe in
`data/baseline-transition/scenario.yaml`:

```powershell
python run.py --mode aviation_preprocessing --example small_with_aviation_passenger
```

The same launcher can override the scenario OpenAP setting if needed:

```powershell
python run.py `
  --mode aviation_preprocessing `
  --example small_with_aviation_passenger `
  --estimate-openap-fuel `
  --openap-mode synthetic
```

Or in VS Code by editing the small config block in [run.py](C:/Manish_REPO/NATM/run.py:1):

```python
selected_mode = "aviation_preprocessing"
selected_example = "small_with_aviation_passenger"
```

The bridge file into the existing aviation model is:

```text
data/<case-name>/aviation_activity_profiles.csv
```

If present in a case folder, NATM merges it onto the aviation fleet stock
baseline during case loading.

For the full preprocessing workflow, outputs, and architecture notes, see:

- `docs/aviation-preprocessing-guide.md`

### Dashboard Setup And Use

If you want to use the NATM Solara/Mesa dashboards, install the optional
dashboard dependencies:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dashboard]
```

Then you can launch any of the four dashboards:

```powershell
solara run dashboard_examples/aviation_passenger_baseline_dashboard.py
solara run dashboard_examples/aviation_cargo_baseline_dashboard.py
solara run dashboard_examples/maritime_cargo_baseline_dashboard.py
solara run dashboard_examples/maritime_passenger_baseline_dashboard.py
```

Each dashboard supports two modes inside the browser:

- `Live case`
- `Saved results`

`Live case` reruns the configured case directly from `data/<case-name>/`.

`Saved results` reads an already generated folder under:

```text
simulation_results/<your-run-name>/
```

In the dashboard UI:

1. open the `Dashboard Source` card
2. choose `Saved results`
3. select the results folder from the dropdown

The saved-results dropdown only shows folders that contain the expected CSV
outputs for that application.

If you already installed the dashboard stack and see a `Starlette.__init__()`
error mentioning `on_startup`, repair the environment with:

```powershell
python -m pip install "starlette<1" "solara-server[starlette]>=1.40"
```

For the full dashboard workflow, see:

- `docs/dashboard-guide.md`

### Run Tests

```powershell
pytest
```

### Typical Development Flow

```powershell
.venv\Scripts\Activate.ps1
pre-commit run --all-files
pytest
python run.py
```

## Outputs

The default `run.py` launcher writes outputs to:

```text
simulation_results/<selected_example>/
```

This folder contains:

- `model_summary.csv`
- `agents.csv`
- `aircraft.csv`
- `aviation_technology.csv`
- `aviation_energy_emissions.csv`
- `aviation_investments.csv`
- `maritime_technology.csv`
- `maritime_energy_emissions.csv`
- `maritime_investments.csv`
- `natm_runs.sqlite`

Named example presets currently included in [run.py](C:/Manish_REPO/NATM/run.py:1):

- `small_with_aviation_passenger`
- `small_with_aviation_cargo`
- `small_with_maritime_cargo`
- `small_with_maritime_passenger`

## Project Layout

- `navaero_transition_model/core/scenario.py`: scenario schema and YAML loader
- `navaero_transition_model/aviation_preprocessing/`: aviation ingestion, enrichment, activity profiling, allocation, calibration, and baseline-building workflow
- `navaero_transition_model/core/policy.py`: plain Python policy/config objects and yearly policy signals
- `navaero_transition_model/core/loaders/`: loader classes and convenience functions for case ingestion
- `navaero_transition_model/core/agent_types/`: parent and specialized Mesa agent classes
- `navaero_transition_model/core/case_inputs/`: case input objects for fleet stock, technology catalog, and scenario tables
- `navaero_transition_model/core/decision_logic/`: pluggable investment/adoption logic implementations
- `navaero_transition_model/core/fleet_management/`: fleet state and fleet-management objects
- `navaero_transition_model/core/environment.py`: shared country-and-corridor world layer
- `navaero_transition_model/core/model.py`: Mesa `Model`, AgentSet activation, and DataCollector output
- `navaero_transition_model/core/database/`: optional SQLite-backed database writing for case inputs and run outputs
- `navaero_transition_model/core/result_exports/`: exporter classes for detailed simulation result tables
- `navaero_transition_model/cli.py`: command-line entry point
- `dashboard_examples/`: small Solara/Mesa dashboard examples
- `docs/dashboard-guide.md`: how to launch dashboards and switch between live and saved-results mode
- `docs/aviation-preprocessing-guide.md`: aviation preprocessing architecture, outputs, and CLI usage
- `docs/architecture.md`: detailed system architecture and runtime flow
- `docs/aviation-passenger-reference.md`: passenger-specific reference for `aviation_scenario.csv`
- `docs/aviation-cargo-scenario-reference.md`: cargo-specific reference for `aviation_scenario.csv` in cargo aviation cases
- `docs/maritime-cargo-reference.md`: cargo-specific reference for `maritime_scenario.csv`
- `docs/maritime-passenger-reference.md`: passenger-specific reference for `maritime_scenario.csv`
- `data/<case-name>/scenario.yaml`: case configuration
- `data/<case-name>/*.csv`: input data for that case

The `baseline-transition` case includes the passenger-specific 3-file input
structure:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

The `baseline-cargo-transition` case uses the same aviation CSV filenames:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

In technology catalogs, `technology_name` is the unique lookup key. For real
aviation datasets this can be a specific aircraft model such as `A320neo`,
`A321XLR`, or `B787-9`. `segment` is still used for demand, market-share,
planned-delivery, activity, and reporting scopes, but it is not part of the
technology identity. The example technology catalogs still include a `segment`
column as optional operating-context metadata, but the model no longer relies
on `technology_name + segment` as a composite key.

The `baseline-maritime-cargo-transition` case uses maritime-sector CSV filenames:

- `maritime_fleet_stock.csv`
- `maritime_technology_catalog.csv`
- `maritime_scenario.csv`

The `baseline-maritime-passenger-transition` case uses the same maritime CSV
filenames:

- `maritime_fleet_stock.csv`
- `maritime_technology_catalog.csv`
- `maritime_scenario.csv`

The fleet stock input can also carry an `investment_logic` column so each
airline agent can select its decision method by name. The current built-in
logic is `legacy_weighted_utility`.

For the passenger scenario CSV contract, see
`docs/aviation-passenger-reference.md`.

For a cargo-only view of the same contract, see
`docs/aviation-cargo-scenario-reference.md`.

For the maritime-passenger scenario CSV contract, see
`docs/maritime-passenger-reference.md`.

For the maritime-cargo scenario CSV contract, see
`docs/maritime-cargo-reference.md`.

For the system-level architecture, see `docs/architecture.md`.

For the dashboard workflow, see `docs/dashboard-guide.md`.

## What The Model Now Captures

- Carbon-price ramp shared across sectors
- Sector-specific clean-fuel subsidies and adoption mandates
- Infrastructure buildout and learning effects
- Yearly transition pressure and effective cost outputs
- Mesa-native activation through `model.agents_by_type[...] .shuffle_do("step")`
- Mesa-native model and agent reporting through `mesa.DataCollector`
- Multiple operator agents per sector with heterogeneous fleet sizes and costs
- Aviation fleet-stock CSV aggregation into airline-specific Mesa agents
- Flexible agent decision logic chosen by `investment_logic` from the input data
- Agent inheritance structure with reusable parent classes for future agent types
- Object-oriented case data, technology catalog, scenario table, fleet, and output exporters
- A shared environment layer with country states and route/corridor effects
- Detailed aviation passenger, aviation cargo, maritime cargo, and maritime passenger outputs for stock, technology diffusion, energy/emissions, and investment activity

## License And Citation

NATM is licensed under the GNU General Public License, version 3 only
(`GPL-3.0-only`). See `LICENSE` for the full license text.

Copyright (C) 2026 Manish Gaebelein-Khanra.

If you use NATM in academic, policy, consulting, or engineering work, please
cite the project repository and any associated publications. GitHub should show
a "Cite this repository" button using the metadata in `CITATION.cff`.

Third-party software dependencies, datasets, and external data sources retain
their own licenses, citation requirements, and terms of use.

## Near-Term Next Steps

1. Replace the sample aviation fleet-stock CSV with calibrated operator and fleet data.
2. Split aviation operator agents further into fleet, route, or airport-linked Mesa agents.
3. Add energy pathways, emissions accounting, and richer reporting outputs.



