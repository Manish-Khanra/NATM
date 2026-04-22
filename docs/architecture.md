# NATM Architecture

This document describes the current software architecture of NATM as it exists
in the repository today.

The current implementation is a Mesa-based aviation-passenger model with a
general structure that can be extended to additional sectors and applications
later.

## 1. Architecture Overview

NATM is organized around six layers:

1. Run and CLI layer
2. Case configuration and input-data layer
3. Mesa model and agent layer
4. Domain and decision-logic layer
5. Environment layer
6. Output and persistence layer

In the current codebase, the active end-to-end path is:

`run.py` or `python -m navaero_transition_model`  
-> `NATMScenario`  
-> `AviationPassengerCaseData`  
-> `NATMModel`  
-> `AviationPassengerAirlineAgent`  
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

### Reporting and database writing

- [result_exports/aviation_exports.py](C:/Manish_REPO/NATM/navaero_transition_model/core/result_exports/aviation_exports.py:1)
  Detailed output exporters.
- [sqlite_store.py](C:/Manish_REPO/NATM/navaero_transition_model/core/database/sqlite_store.py:1)
  SQLite persistence for inputs and outputs.

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

### 3.3 Input-data assembly

For the aviation-passenger path, `NATMModel` loads:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

These are wrapped by `AviationPassengerCaseData`, which bundles:

- normalized fleet stock
- a `TechnologyCatalog`
- a `ScenarioTable`

This layer also performs validation. In particular, the current capacity
planning implementation requires:

- `passenger_km_demand`
- `operator_market_share`

for all required year/scope combinations.

### 3.4 Model construction

`NATMModel` is a Mesa `Model`. During initialization it:

1. stores the scenario
2. creates the shared environment
3. loads aviation-passenger case data if the case enables aviation/passenger
4. creates one `AviationPassengerAirlineAgent` per `(operator_name, operator_country)`
5. builds a `mesa.DataCollector`
6. records the initial model snapshot and detailed aircraft snapshot

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

Important detail:

- `AviationPassengerAirlineAgent` is the active agent class used by the current
  case path.
- `TransportOperatorAgent` and the sector-level aviation/maritime operator
  classes remain in the architecture as reusable parent/general-purpose agent
  types for future extensions.

### 4.3 Why the current aviation agent is specialized

`AviationPassengerAirlineAgent` is more detailed than the generic transport
operator because it owns:

- a per-aircraft fleet
- a technology catalog
- a scenario table
- a selected investment logic plugin
- ETS balance state
- airline-specific economic/environmental preferences

This is what makes NATM both Mesa-native and still domain-specific enough for
aviation-passenger decisions.

## 5. Input Layer

### 5.1 `AviationPassengerCaseData`

`AviationPassengerCaseData` is the main aviation-passenger case bundle.

Responsibilities:

- read and normalize fleet stock
- load technology catalog
- load scenario table
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

Each row represents one aircraft in the starting fleet.

### 5.3 Technology catalog

The technology catalog is loaded into `TechnologyCatalog`.

Responsibilities:

- validate required technology columns
- provide all candidate technologies for a segment
- return a specific technology row by name
- provide the default technology for a segment

This is the canonical source for:

- technology cost/performance assumptions
- fuel carriers
- emissions factors
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

`Fleet` is a domain object that owns the airlineâ€™s aircraft dataframe and
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
2. replace due aircraft
3. add growth aircraft if capacity gaps remain

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
- passenger-km capacity planning for growth

### 7.3 Current growth architecture

The old `market_growth` rule is no longer active.

Growth now follows this business-style flow:

1. read `passenger_km_demand` by `country + segment`
2. allocate that demand using `operator_market_share`
3. compute airline segment capacity from actual fleet and effective load factor
4. apply `planned_delivery_count` first if present
5. endogenously add aircraft only if a residual capacity gap remains

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

Detailed aviation outputs are handled by exporter classes:

- `AircraftStockExporter`
- `AviationTechnologyExporter`
- `AviationEnergyEmissionsExporter`
- `AviationInvestmentExporter`
- `DetailedOutputWriter`

These exporters use the stored aircraft history snapshots to produce flat CSV
tables such as:

- `aircraft.csv`
- `aviation_technology.csv`
- `aviation_energy_emissions.csv`
- `aviation_investments.csv`

This split keeps `DataCollector` focused on summary reporting while allowing
rich domain-specific output tables for analysis.

## 10. SQLite Persistence

`SQLiteSimulationStore` writes both inputs and outputs of a run into a SQLite
database.

It stores:

- run metadata
- aviation fleet input
- technology catalog input
- aviation scenario input
- model summary output
- agent output
- aircraft output
- technology output
- energy/emissions output
- investment output

The implementation also includes a Windows/workspace-friendly fallback strategy
for SQLite journaling issues.

## 11. Case and Configuration Model

The current case structure is:

```text
data/
  <case-name>/
    scenario.yaml
    aviation_fleet_stock.csv
    aviation_technology_catalog.csv
    aviation_scenario.csv
    countries.csv
    corridors.csv
```

The YAML is intentionally small and only declares:

- case identity
- start and end year
- enabled sector/application combinations

Detailed behavior belongs in the CSV inputs, not in the YAML.

## 12. Active vs Future Architecture

### Active today

- aviation sector
- passenger application
- airline agents with aircraft fleets
- case-based CSV inputs
- detailed exporter outputs
- optional SQLite persistence

### Present as extension points, but not active in the current case

- sector-generic transport operator agents
- maritime sector placeholders
- multiple investment logic implementations
- richer hub-level or airport-level infrastructure constraints
- additional agent types such as airports, fuel suppliers, OEMs, or policy agents

## 13. Design Principles

The current architecture follows these principles:

- Mesa-native model and agents for simulation lifecycle
- case-based inputs instead of ID-heavy relational spreadsheets
- object-oriented domain separation for fleets, catalogs, scenarios, reporting, and database writing
- pluggable decision logic instead of hard-wiring one investment rule into the agent
- flat CSV outputs plus optional SQLite for analysis and persistence
- minimal YAML, richer CSVs

## 14. Current Limitations

The architecture is clean enough for growth, but some boundaries are still
deliberately simple:

- only aviation-passenger is fully implemented
- hub-level infrastructure is stored (`main_hub`) but not yet driving decisions
- the environment is country/corridor-based, not yet airport-network-based
- market-share allocation is currently fixed-share rather than competitive
- `run.py` and `cli.py` overlap slightly because one is optimized for daily use
  and the other for command-line control

## 15. Recommended Reading Order

For someone new to the codebase, this is the best order:

1. [run.py](C:/Manish_REPO/NATM/run.py:1)
2. [cli.py](C:/Manish_REPO/NATM/navaero_transition_model/cli.py:1)
3. [scenario.py](C:/Manish_REPO/NATM/navaero_transition_model/core/scenario.py:1)
4. [aviation_passenger_case.py](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs/aviation_passenger_case.py:1)
5. [model.py](C:/Manish_REPO/NATM/navaero_transition_model/core/model.py:1)
6. [aviation_passenger_airline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/aviation_passenger_airline.py:1)
7. [legacy_weighted_utility.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility.py:1)
8. [fleet.py](C:/Manish_REPO/NATM/navaero_transition_model/core/fleet_management/fleet.py:1)
9. [aviation_exports.py](C:/Manish_REPO/NATM/navaero_transition_model/core/result_exports/aviation_exports.py:1)
10. [sqlite_store.py](C:/Manish_REPO/NATM/navaero_transition_model/core/database/sqlite_store.py:1)

That path follows the same order the system itself uses during a run.






