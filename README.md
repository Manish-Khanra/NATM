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

The current `baseline-transition` case is set up as an aviation-passenger test
case, while the architecture is designed to extend to aviation cargo and
maritime applications as the model grows.

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
- `natm_runs.sqlite`

## Project Layout

- `navaero_transition_model/core/scenario.py`: scenario schema and YAML loader
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
- `docs/architecture.md`: detailed system architecture and runtime flow
- `docs/aviation-scenario-reference.md`: reference for `aviation_scenario.csv`, including variable groups, variable names, and scope rules
- `docs/aviation-passenger-mesa-port.md`: port plan from the old Melodie aviation-passenger model
- `docs/aviation-passenger-render-gap-map.md`: strict old-vs-new aviation-passenger fidelity checklist
- `data/<case-name>/scenario.yaml`: case configuration
- `data/<case-name>/*.csv`: input data for that case

The `baseline-transition` case now also includes aviation-passenger intake
templates for the future 3-file structure:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

The fleet stock input can also carry an `investment_logic` column so each
airline agent can select its decision method by name. The current built-in
logic is `legacy_weighted_utility`.

For the full scenario CSV contract, see
`docs/aviation-scenario-reference.md`.

For the system-level architecture, see `docs/architecture.md`.

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
- Detailed aviation-passenger outputs for aircraft stock, technology diffusion, energy/emissions, and investment activity

## Near-Term Next Steps

1. Replace the sample aviation fleet-stock CSV with calibrated operator and fleet data.
2. Split aviation operator agents further into fleet, route, or airport-linked Mesa agents.
3. Add energy pathways, emissions accounting, and richer reporting outputs.



