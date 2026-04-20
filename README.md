# NATM

NATM stands for NavAero Transition Model.

This repository contains the first development scaffold for a transport
transition model. The starter version focuses on a simple scenario loader, a
lightweight transition simulation, and a command-line entry point we can grow
into a fuller agent-based model. The implementation now uses Mesa-native
`Model`, `AgentSet`, `Agent`, and `DataCollector` architecture with multiple
operator agents in each sector. The current `baseline-transition` case is set up
as an aviation-passenger test case, while the codebase still keeps room for
future maritime cases.

## Quick Start

### PowerShell

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
natm --case baseline-transition --output outputs/baseline.csv
```

If you want the easiest VS Code entrypoint, run:

```powershell
python run.py
```

That launcher writes the results automatically into:

```text
outputs/<selected_example>/
```

including `model_summary.csv`, the detailed CSV tables, and `natm_runs.sqlite`.

To export the richer Mesa result tables as well:

```powershell
natm --case baseline-transition --output outputs/baseline.csv --details-dir outputs/baseline-details
```

To persist both case inputs and run outputs into SQLite:

```powershell
natm --case baseline-transition --output outputs/baseline.csv --details-dir outputs/baseline-details --sqlite-db outputs/natm_runs.sqlite
```

### Run Tests

```powershell
pytest
```

## Project Layout

- `src/natm/core/scenario.py`: scenario schema and YAML loader
- `src/natm/core/policy.py`: plain Python policy/config objects and yearly policy signals
- `src/natm/core/aviation_passenger_loader.py`: compatibility loader wrapping the OO case-data layer
- `src/natm/core/agent_types/`: parent and specialized Mesa agent classes
- `src/natm/core/case_data/`: case/input domain objects for fleet stock, technology catalog, and scenario tables
- `src/natm/core/decision_logic/`: pluggable investment/adoption logic implementations
- `src/natm/core/domain/`: reusable domain objects such as fleet management
- `src/natm/core/environment.py`: shared country-and-corridor world layer
- `src/natm/core/model.py`: Mesa `Model`, AgentSet activation, and DataCollector output
- `src/natm/core/outputs/`: exporter classes for detailed simulation outputs
- `src/natm/core/storage/`: optional SQLite-backed storage for case inputs and run outputs
- `src/natm/cli.py`: command-line entry point
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
