# NATM

NATM stands for NavAero Transition Model.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Mesa](https://img.shields.io/badge/agent--based-Mesa-2a6f97.svg)](https://mesa.readthedocs.io/)
[![Dashboard](https://img.shields.io/badge/dashboard-Solara-ffb703.svg)](docs/dashboard-guide.md)
[![DOI](https://img.shields.io/badge/DOI-10.1016%2Fj.nexus.2025.100557-blue.svg)](https://doi.org/10.1016/j.nexus.2025.100557)
[![Status](https://img.shields.io/badge/status-active%20development-orange.svg)](#near-term-next-steps)

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

## Highlights

- Mesa-based agent-based simulation for aviation and maritime transition pathways
- Aviation passenger, aviation cargo, maritime cargo, and maritime passenger cases
- Flexible operator decision logic selected through case input data
- Optional ambiguity-aware investment logic over multiple future scenarios
- Demand-driven aviation growth using passenger-km and tonne-km planning inputs
- Optional OpenSky/OpenAP preprocessing for aviation activity, fuel, and emissions
- Structured CSV and SQLite outputs for analysis and dashboards
- Solara dashboards for live cases, saved runs, preprocessing outputs, and route maps

## Documentation

- [Architecture](docs/architecture.md)
- [Aviation preprocessing guide](docs/aviation-preprocessing-guide.md)
- [Dashboard guide](docs/dashboard-guide.md)
- [Aviation passenger input reference](docs/aviation-passenger-reference.md)
- [Aviation cargo input reference](docs/aviation-cargo-scenario-reference.md)
- [Maritime cargo input reference](docs/maritime-cargo-reference.md)
- [Maritime passenger input reference](docs/maritime-passenger-reference.md)

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
natm --case baseline-passenger-transition --output simulation_results/baseline.csv
```

To export the richer Mesa result tables as well:

```powershell
natm --case baseline-passenger-transition --output simulation_results/baseline.csv --details-dir simulation_results/baseline-details
```

To persist both case inputs and run outputs into SQLite:

```powershell
natm --case baseline-passenger-transition --output simulation_results/baseline.csv --details-dir simulation_results/baseline-details --sqlite-db simulation_results/natm_runs.sqlite
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
  --stock-input data\baseline-passenger-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-passenger-transition\aviation_technology_catalog.csv `
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
  --stock-input data\baseline-passenger-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-passenger-transition\aviation_technology_catalog.csv `
  --calibration-input data\examples\aviation_preprocessing\germany_calibration_input.csv `
  --estimate-openap-fuel `
  --openap-mode synthetic
```

This writes OpenAP flight, aircraft-type, route, mapping-log, and validation
outputs into `data/processed/aviation/` and enriches
`aviation_activity_profiles.csv` for the core Mesa simulation.

You can also run the scenario-defined preprocessing flow from `run.py`. The
baseline passenger case stores its preprocessing recipe in
`data/baseline-passenger-transition/scenario.yaml`:

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

Then you can launch the standard live/saved-results dashboard:

```powershell
solara run dashboard_examples/common_case_dashboard.py
```

The standalone cartographic dashboard opens a browser-native deck.gl map for
aviation result folders:

```powershell
solara run dashboard_examples/cartographic_dashboard.py
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

The cartographic dashboard reads `simulation_results/<your-run-name>/`
directly. When postprocessed `airport_fuel_demand.csv` and
`route_energy_flow.csv` files exist, it uses those map-ready airport and route
layers. Otherwise, it uses `aircraft.csv` for simulated years and airport
demand, and falls back to processed aviation route geometry when route-level map
outputs are not present.

To create dashboard-ready airport fuel-demand and route-flow files after a run:

```powershell
natm-airport-fuel-allocation --results simulation_results/<your-run-name>
```

If the new command is not recognized before reinstalling the editable package,
use:

```powershell
python -m navaero_transition_model.postprocessing.airport_fuel_allocation_cli --results simulation_results/<your-run-name>
```

This postprocessor is separate from the investment/adoption simulation. It uses
flightlist/OpenAP sequences when aircraft identifiers match; otherwise it falls
back to synthetic allocation from simulated aircraft energy and processed route
shares.

Dashboard notes:

- the normal dashboards now include an `Emissions` panel that can show all
  detected pollutant columns, including OpenAP `co2_kg`, `h2o_kg`, `nox_kg`,
  `co_kg`, `hc_kg`, `soot_kg`, and `sox_kg`
- pollutant totals are displayed in tonnes
- the cartographic map tooltips include metric labels and units
- the cartographic metric buttons use readable names, with a display-unit
  toggle for convertible metrics such as fuel uplift mass
- cartographic MWh metrics switch to TWh at `1,000 MWh`
- cartographic fuel uplift mass and pollutant metrics switch from kg to tonnes
  for large displayed values

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
- `aviation_robust_frontier.csv`
- `maritime_robust_frontier.csv`
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

The `baseline-passenger-transition` case includes the passenger-specific 3-file input
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
operator agent can select its decision method by name. Legacy behavior is
available for every sector through `legacy_weighted_utility`. Older
sector-specific legacy names are still accepted as aliases for existing cases.

The ambiguity-aware extension also uses one strategy name for every sector:
`ambiguity_aware_utility`. Older sector-specific ambiguity-aware names are
still accepted as aliases for existing cases.

Fleet stock can optionally include `decision_attitude` with
`risk_neutral`, `risk_averse`, or `ambiguity_averse`. If it is missing, NATM
defaults to `risk_neutral`. The column only changes behavior for the
ambiguity-aware logic; legacy weighted-utility decisions are unchanged.

Scenario CSVs can optionally include `scenario_id`. If the column is missing,
all rows are treated as `baseline`. When present, the ambiguity-aware logic
evaluates candidate technologies over configured future scenarios while keeping
the existing blank-scope and specificity matching rules.

Minimal `scenario.yaml` example:

```yaml
ambiguity_aware_decision:
  enabled: true
  scenario_ids:
    - baseline
    - high_fuel_price
    - delayed_infrastructure
  probabilities:
    baseline: 0.5
    high_fuel_price: 0.3
    delayed_infrastructure: 0.2
  ambiguity:
    enabled: true
    probability_deviation: 0.1
  expected_shortfall_alpha: 0.2
  robust_metric: worst_case_expected_utility
```

This is an ambiguity-aware extension of the existing utility-based fleet
diffusion model. The model still simulates technology diffusion through fleet
replacement and growth, but candidate technologies can now be evaluated over a
set of possible future scenarios. Risk-neutral actors maximise expected
utility, risk-averse actors use downside-sensitive expected shortfall, and
ambiguity-averse actors use worst-case probability-weighted criteria over a
bounded ambiguity set.

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

## Citing NATM

If you use NATM in your research, policy analysis, consulting, or engineering
work, please cite the following paper:

- Manish Khanra, Shashank Deepak Prabhu, Martin Wietschel,
  [Estimating energy demand for decarbonising the aviation and maritime fleets
  of Germany: An agent-based technology diffusion approach considering
  investment behaviour](https://doi.org/10.1016/j.nexus.2025.100557),
  published in *Energy Nexus*, Volume 20, 2025, Article 100557.

Please use the following BibTeX to cite the work:

```bibtex
@article{khanra2025estimating,
  title = {Estimating energy demand for decarbonising the aviation and maritime fleets of Germany: An agent-based technology diffusion approach considering investment behaviour},
  author = {Khanra, Manish and Prabhu, Shashank Deepak and Wietschel, Martin},
  journal = {Energy Nexus},
  volume = {20},
  pages = {100557},
  year = {2025},
  issn = {2772-4271},
  doi = {10.1016/j.nexus.2025.100557},
  url = {https://www.sciencedirect.com/science/article/pii/S2772427125001974},
  keywords = {Hard-to-abate sector, Agent-based model, Technology diffusion, Demand analysis, Aviation, Maritime}
}
```

For citing a specific software version of NATM, use the repository citation
metadata in `CITATION.cff`.

## License

NATM is licensed under the GNU General Public License, version 3 only
(`GPL-3.0-only`). See `LICENSE` for the full license text.

Copyright (C) 2026 Manish Gaebelein-Khanra.

Third-party software dependencies, datasets, and external data sources retain
their own licenses, citation requirements, and terms of use.



