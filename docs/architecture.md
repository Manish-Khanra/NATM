# NATM Architecture

This document describes the current software architecture of NATM as it exists
in the repository today.

The current implementation is a Mesa-based transport model with working
aviation-passenger, aviation-cargo, maritime-cargo, and maritime-passenger
applications, and a general structure that can be extended to additional
sectors and applications later.

## 1. Architecture Overview

NATM is organized around seven layers:

1. Run and CLI layer
2. Aviation preprocessing layer
3. Case configuration and input-data layer
4. Mesa model and agent layer
5. Domain and decision-logic layer
6. Environment layer
7. Output and persistence layer

In the current codebase, the active end-to-end path is:

`run.py` or `python -m navaero_transition_model`  
-> `NATMScenario`  
-> case input bundle (`AviationPassengerCaseData`, `AviationCargoCaseData`, `MaritimeCargoCaseData`, or `MaritimePassengerCaseData`)  
-> `NATMModel`  
-> application agent (`AviationPassengerAirlineAgent`, `AviationCargoAirlineAgent`, `MaritimeCargoShiplineAgent`, or `MaritimePassengerShiplineAgent`)  
-> decision logic + fleet updates  
-> `DataCollector` + detailed exporters + optional SQLite

## 2. Repository Structure

### Entry and orchestration

- [run.py](C:/Manish_REPO/NATM/run.py:1)
  Reference-style launcher for VS Code and simple named examples.
- [cli.py](C:/Manish_REPO/NATM/navaero_transition_model/cli.py:1)
  Standard command-line entrypoint used by `python -m navaero_transition_model`.

### Core simulation

- [model.py](C:/Manish_REPO/NATM/navaero_transition_model/core/model.py:1)
  Top-level Mesa `Model` implementation.
- [agent_types](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types)
  Agent hierarchy and agent-related shared types.
- [decision_logic](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic)
  Pluggable technology-adoption and investment logic.
- [fleet_management](C:/Manish_REPO/NATM/navaero_transition_model/core/fleet_management)
  Domain objects such as fleet management.
- [environment.py](C:/Manish_REPO/NATM/navaero_transition_model/core/environment.py:1)
  Shared world/environment state.

### Input and scenario handling

- [scenario.py](C:/Manish_REPO/NATM/navaero_transition_model/core/scenario.py:1)
  Minimal case YAML loader.
- [case_inputs](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs)
  Fleet stock, technology catalog, and scenario-table abstractions.
- [loaders](C:/Manish_REPO/NATM/navaero_transition_model/core/loaders)
  Thin compatibility wrapper around the case-data layer.

### Aviation preprocessing

- [aviation_preprocessing](C:/Manish_REPO/NATM/navaero_transition_model/aviation_preprocessing)
  Aviation ingestion, enrichment, activity profiling, allocation, calibration,
  and baseline-building workflow.

### Reporting and database writing

- [result_exports/aviation_exports.py](C:/Manish_REPO/NATM/navaero_transition_model/core/result_exports/aviation_exports.py:1)
  Detailed output exporters.
- [sqlite_store.py](C:/Manish_REPO/NATM/navaero_transition_model/core/database/sqlite_store.py:1)
  SQLite persistence for inputs and outputs.
- [dashboard_examples](C:/Manish_REPO/NATM/dashboard_examples)
  Solara/Mesa dashboards for live cases and saved results.

## 3. Runtime Flow

### 3.1 Launch

There are two supported launch paths:

- `python run.py`
- `python -m navaero_transition_model --case <case-name>`

`run.py` is the more user-friendly launcher for daily work. It resolves a named
example to a case folder under `data/`, runs the model, and writes outputs to
`simulation_results/<selected_example>/`.

### 3.2 Case loading

The case starts with [scenario.yaml](C:/Manish_REPO/NATM/data/baseline-transition/scenario.yaml:1),
which is loaded by `NATMScenario`.

`NATMScenario` currently stores:

- `name`
- `start_year`
- `end_year`
- `sectors`
- `base_path`

The YAML is intentionally minimal. Case-specific behavior is not encoded in the
YAML itself; it is primarily driven by the CSV inputs in the case folder.

### 3.2a Aviation preprocessing path

The aviation preprocessing layer is designed to build empirical baseline inputs
without polluting:

- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

Instead it keeps observed and derived aviation baseline data in separate files,
primarily under:

- `data/processed/aviation/`

The main preprocessing stages are:

1. stock cleaning
2. OpenSky aircraft metadata ingestion
3. stock-to-OpenSky matching
4. OpenSky / Zenodo flightlist ingestion
5. empirical activity-profile construction
6. German airport / regional allocation
7. Germany calibration-target construction
8. enriched aviation baseline assembly

The final bridge file into the aviation case architecture is:

- `aviation_activity_profiles.csv`

If that file exists in a case directory, the aviation case-data layer loads and
merges it onto the baseline fleet stock.

### 3.3 Input-data assembly

For the aviation-passenger path, `NATMModel` loads:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`
- `aviation_activity_profiles.csv` if present

These are wrapped by `AviationPassengerCaseData`, which bundles:

- normalized fleet stock
- a `TechnologyCatalog`
- a `ScenarioTable`

For the aviation-cargo path, `NATMModel` loads:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`
- `aviation_activity_profiles.csv` if present

These are wrapped by `AviationCargoCaseData`.

This layer also performs validation. In particular, the current capacity
planning implementation requires:

- `passenger_km_demand` for aviation passenger
- `freight_tonne_km_demand` for aviation cargo
- `freight_tonne_km_demand` for maritime cargo
- `passenger_km_demand` for maritime passenger
- `operator_market_share`

for all required year/scope combinations.

### 3.4 Model construction

`NATMModel` is a Mesa `Model`. During initialization it:

1. stores the scenario
2. creates the shared environment
3. loads aviation-passenger case data if the case enables aviation/passenger
4. loads any enabled application case data
5. creates one application-specific operator agent per `(operator_name, operator_country)`
6. builds a `mesa.DataCollector`
7. records the initial model snapshot and detailed fleet snapshot

### 3.5 Simulation step

Each yearly step in `NATMModel.step()` does the following:

1. update current sector context
2. activate agents through Mesa `AgentSet.shuffle_do("step")`
3. update the shared environment using the latest policy signal and agent state
4. record a yearly model snapshot
5. collect Mesa model/agent outputs
6. record detailed aircraft history for exporter use

The model year is derived from:

- `scenario.start_year + model.steps`

So the initial snapshot is the start year, and the first active decision step
occurs in the following simulation year.

## 4. Mesa Layer

### 4.1 Model

[NATMModel](C:/Manish_REPO/NATM/navaero_transition_model/core/model.py:43) is the top-level Mesa
container. It is responsible for:

- loading case data
- instantiating agents
- computing current policy signals from the scenario table
- maintaining sector-level market context
- activating agents
- updating the environment
- collecting outputs

### 4.2 Agent hierarchy

The current agent hierarchy is:

- `BaseOperatorAgent`
- `TransportOperatorAgent`
- `AviationOperatorAgent`
- `MaritimeOperatorAgent`
- `AviationPassengerAirlineAgent`
- `AviationCargoAirlineAgent`
- `MaritimeCargoShiplineAgent`
- `MaritimePassengerShiplineAgent`

Important detail:

- `AviationPassengerAirlineAgent` and `AviationCargoAirlineAgent` are the active
  agent classes used by the current case paths.
- `TransportOperatorAgent` and the sector-level aviation/maritime operator
  classes remain in the architecture as reusable parent/general-purpose agent
  types for future extensions.

### 4.3 Why the current aviation agents are specialized

The aviation application agents are more detailed than the generic transport
operator because they own:

- a per-aircraft fleet
- a technology catalog
- a scenario table
- a selected investment logic plugin
- ETS balance state
- airline-specific economic/environmental preferences

This is what makes NATM both Mesa-native and still domain-specific enough for
aviation and maritime fleet-transition decisions.

## 5. Input Layer

### 5.1 `AviationPassengerCaseData`

`AviationPassengerCaseData`, `AviationCargoCaseData`,
`MaritimeCargoCaseData`, and `MaritimePassengerCaseData` are the current
application input bundles.

Responsibilities:

- read and normalize fleet stock
- load technology catalog
- load scenario table
- optionally load and merge aviation activity profiles
- expose grouped operator fleets
- validate required capacity-planning inputs

### 5.2 Fleet stock

Fleet stock is loaded from `aviation_fleet_stock.csv`.

Normalization includes:

- column alias mapping
- segment derivation from `Haul`
- passenger-flag derivation
- `investment_logic` defaulting
- operator-key construction
- preservation of empirical baseline fields such as `registration`, `icao24`,
  `annual_distance_km_base`, and `baseline_energy_demand`

Each row represents one aircraft in the starting fleet.

If `aviation_activity_profiles.csv` exists in the case folder, the aviation
case-input layer also merges:

- registration-level profiles where possible
- `icao24`-level profiles where possible
- type-level defaults
- segment-level fallbacks

### 5.3 Technology catalog

The technology catalog is loaded into `TechnologyCatalog`.

Responsibilities:

- validate required technology columns
- provide candidate technology rows for investment logic
- return a specific technology row by unique `technology_name`
- provide a fallback default technology for a segment when stock data does not
  name one explicitly

This is the canonical source for:

- technology cost/performance assumptions
- fuel carriers
- emissions factors
- model-specific efficiency assumptions such as `kilometer_per_kwh`

`technology_name` is the technology identity. For empirical aviation cases this
can be a specific aircraft model such as `A320neo`, `A321XLR`, or `B787-9`.
`segment` remains useful for demand, market-share, planned-delivery, activity,
and reporting scopes, but it is no longer part of the technology lookup key.
In the technology catalog, `segment` is optional context or a legacy fallback,
not part of the unique identifier. The example catalogs still keep it as
operating-context metadata so defaults and compatibility filters stay readable.

Observed stock, activity, and calibration data are intentionally **not** moved
into the technology catalog.
- service-entry restrictions
- seat layout and trip assumptions

### 5.4 Scenario table

`ScenarioTable` loads the wide yearly CSV and also stores a long internal form.

Responsibilities:

- resolve single scenario values with specificity matching
- return matching rows when multi-row logic is needed
- support generic rows and more specific overrides

This is how policy, demand, prices, availability flags, and planned deliveries
are parameterized.

## 6. Domain Layer

### 6.1 Fleet

`Fleet` is a domain object that owns the operator fleet dataframe and
encapsulates fleet operations.

Responsibilities:

- prepare the starting fleet state
- initialize replacement years
- update annual energy/emissions/operating metrics
- determine due replacements
- apply a technology decision to a specific aircraft
- add new aircraft from a template
- create yearly fleet snapshots for exporters

Why this matters:

Without `Fleet`, too much dataframe manipulation would be embedded directly in
the agent class. The fleet object keeps the airline agent focused on behavior
coordination instead of low-level row mutation.

## 7. Decision-Logic Layer

### 7.1 Decision-logic boundary

Decision logic is intentionally modeled as a plugin-style layer under
`navaero_transition_model/core/decision_logic/`.

The active implementation is:

- `legacy_weighted_utility`

The agent selects the logic by name from the fleet input column:

- `investment_logic`

This means future investment/adoption methods can be added without rewriting the
agent architecture.

### 7.2 What the current logic does

`LegacyWeightedUtilityLogic` performs three major tasks each year:

1. update existing fleet operating metrics
2. replace due aircraft or vessels
3. add growth aircraft or vessels if capacity gaps remain

The current technology selection combines:

- economic utility
- environmental utility
- policy bonus

Important behaviors in the current logic:

- technology availability filtering
- infrastructure availability filtering
- SAF pathway availability filtering
- ETS allowance accounting
- NPV/payback-style evaluation
- planned deliveries before endogenous additions
- demand-driven yearly capacity planning for growth

### 7.3 Current growth architecture

The old `market_growth` rule is no longer active.

Growth now follows this business-style flow:

1. read `passenger_km_demand` or `freight_tonne_km_demand` by `country + segment`
2. allocate that demand using `operator_market_share`
3. compute operator segment capacity from actual fleet and effective load factor
4. apply `planned_delivery_count` first if present
5. endogenously add assets only if a residual capacity gap remains

This keeps growth in the decision-logic layer while making it demand-driven
instead of using a simple percentage-growth heuristic.

## 8. Environment Layer

`TransitionEnvironment` is the shared world layer.

It is not a grid world; instead, it models:

- country-level environment state
- corridor-level connectivity and clean-fuel corridor effects

Main environment concepts:

- `CountryEnvironmentState`
- `CountryEnvironmentSignal`
- `Corridor`

Responsibilities:

- load environment inputs from `countries.csv` and `corridors.csv`
- create missing countries on demand
- provide a country/sector signal to each agent
- update infrastructure, fuel availability, and policy alignment over time

This allows the model to connect agents through a shared external system rather
than only through direct agent-to-agent interaction.

## 9. Output Layer

NATM has two output styles.

### 9.1 Mesa `DataCollector`

The `DataCollector` is used for stable low-dimensional outputs:

- yearly model summary
- yearly agent summary

This is the right place for top-level indicators and agent aggregates.

### 9.2 Detailed exporters

Detailed outputs are handled by exporter classes:

- `AircraftStockExporter`
- `AviationTechnologyExporter`
- `AviationEnergyEmissionsExporter`
- `AviationInvestmentExporter`
- `MaritimeTechnologyExporter`
- `MaritimeEnergyEmissionsExporter`
- `MaritimeInvestmentExporter`
- `DetailedOutputWriter`

These exporters use the stored aircraft history snapshots to produce flat CSV
tables such as:

- `aircraft.csv`
- `aviation_technology.csv`
- `aviation_energy_emissions.csv`
- `aviation_investments.csv`
- `maritime_technology.csv`
- `maritime_energy_emissions.csv`
- `maritime_investments.csv`

This split keeps `DataCollector` focused on summary reporting while allowing
rich domain-specific output tables for analysis.

## 10. Dashboard Layer

NATM also includes a Solara/Mesa dashboard layer under
`dashboard_examples/`.

The dashboards support two modes:

1. `Live case`
2. `Saved results`

### 10.1 Live case mode

In live mode, the dashboard:

- resolves a case from `data/<case-name>/`
- instantiates `NATMModel`
- runs the simulation in the dashboard session
- visualizes live model and exporter outputs

### 10.2 Saved results mode

In saved-results mode, the dashboard:

- reads previously generated CSV outputs from `simulation_results/<run-name>/`
- does not rerun the model
- visualizes the stored outputs directly

This makes the dashboard useful both for:

- quick live experimentation
- exploring archived runs

### 10.3 Shared dashboard architecture

The dashboard entrypoints for the four current applications are thin wrappers:

- `aviation_passenger_baseline_dashboard.py`
- `aviation_cargo_baseline_dashboard.py`
- `maritime_cargo_baseline_dashboard.py`
- `maritime_passenger_baseline_dashboard.py`

They all use:

- `dashboard_examples/common_case_dashboard.py`

That shared helper provides:

- common live/saved-results switching
- shared chart layout
- results-folder loading
- shared energy conversion for display in `TWh`
- application-specific chart binding through frame-getter functions

## 11. SQLite Persistence

`SQLiteSimulationStore` writes both inputs and outputs of a run into a SQLite
database.

It stores:

- run metadata
- aviation fleet input
- technology catalog input
- aviation scenario input
- maritime fleet input
- maritime technology catalog input
- maritime scenario input
- model summary output
- agent output
- aircraft output
- technology output
- energy/emissions output
- investment output

The implementation also includes a Windows/workspace-friendly fallback strategy
for SQLite journaling issues.

## 12. Case and Configuration Model

The current case structure is:

```text
data/
  <case-name>/
    scenario.yaml
    aviation_fleet_stock.csv
    aviation_technology_catalog.csv
    aviation_scenario.csv
    maritime_fleet_stock.csv
    maritime_technology_catalog.csv
    maritime_scenario.csv
    countries.csv
    corridors.csv
```

The YAML is intentionally small and only declares:

- case identity
- start and end year
- enabled sector/application combinations

Detailed behavior belongs in the CSV inputs, not in the YAML.

## 13. Active vs Future Architecture

### Active today

- aviation sector
- passenger application
- cargo application
- maritime cargo application
- airline agents with aircraft fleets
- shipline agents with vessel fleets
- case-based CSV inputs
- detailed exporter outputs
- optional SQLite persistence

### Present as extension points, but not active in the current case

- sector-generic transport operator agents
- maritime sector placeholders
- multiple investment logic implementations
- richer hub-level or airport-level infrastructure constraints
- additional agent types such as airports, fuel suppliers, OEMs, or policy agents

## 14. Design Principles

The current architecture follows these principles:

- Mesa-native model and agents for simulation lifecycle
- case-based inputs instead of ID-heavy relational spreadsheets
- object-oriented domain separation for fleets, catalogs, scenarios, reporting, and database writing
- pluggable decision logic instead of hard-wiring one investment rule into the agent
- flat CSV outputs plus optional SQLite for analysis and persistence
- minimal YAML, richer CSVs

## 15. Current Limitations

The architecture is clean enough for growth, but some boundaries are still
deliberately simple:

- aviation passenger, aviation cargo, and maritime cargo are implemented
- hub-level infrastructure is stored (`main_hub`) but not yet driving decisions
- the environment is country/corridor-based, not yet airport-network-based
- market-share allocation is currently fixed-share rather than competitive
- `run.py` and `cli.py` overlap slightly because one is optimized for daily use
  and the other for command-line control
- saved-results dashboards currently expect the standard NATM CSV output filenames

## 16. Recommended Reading Order

For someone new to the codebase, this is the best order:

1. [run.py](C:/Manish_REPO/NATM/run.py:1)
2. [cli.py](C:/Manish_REPO/NATM/navaero_transition_model/cli.py:1)
3. [scenario.py](C:/Manish_REPO/NATM/navaero_transition_model/core/scenario.py:1)
4. [aviation_passenger_case.py](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs/aviation_passenger_case.py:1)
5. [aviation_cargo_case.py](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs/aviation_cargo_case.py:1)
6. [maritime_cargo_case.py](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs/maritime_cargo_case.py:1)
7. [model.py](C:/Manish_REPO/NATM/navaero_transition_model/core/model.py:1)
8. [aviation_passenger_airline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/aviation_passenger_airline.py:1)
9. [aviation_cargo_airline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/aviation_cargo_airline.py:1)
10. [maritime_cargo_shipline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/maritime_cargo_shipline.py:1)
11. [maritime_passenger_shipline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/maritime_passenger_shipline.py:1)
12. [legacy_weighted_utility.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility.py:1)
13. [legacy_weighted_utility_cargo.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility_cargo.py:1)
14. [legacy_weighted_utility_maritime_cargo.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility_maritime_cargo.py:1)
15. [legacy_weighted_utility_maritime_passenger.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility_maritime_passenger.py:1)
16. [fleet.py](C:/Manish_REPO/NATM/navaero_transition_model/core/fleet_management/fleet.py:1)
17. [aviation_exports.py](C:/Manish_REPO/NATM/navaero_transition_model/core/result_exports/aviation_exports.py:1)
18. [sqlite_store.py](C:/Manish_REPO/NATM/navaero_transition_model/core/database/sqlite_store.py:1)

That path follows the same order the system itself uses during a run.






