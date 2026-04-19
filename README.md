# NATM

NATM stands for NavAero Transition Model.

This repository contains the first development scaffold for a joint aviation and
maritime transition model. The starter version focuses on a simple scenario
loader, a lightweight transition simulation, and a command-line entry point we
can grow into a fuller agent-based model. The current baseline now includes
sector-level policy levers, fuel-cost pressure, and infrastructure readiness.
The implementation now uses Mesa-native `Model`, `AgentSet`, `Agent`, and
`DataCollector` architecture with multiple operator agents in each sector.

## Quick Start

### PowerShell

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
natm --config config/default.yaml --output outputs/baseline.csv
```

### Run Tests

```powershell
pytest
```

## Project Layout

- `src/natm/core/scenario.py`: scenario schema and YAML loader
- `src/natm/core/policy.py`: plain Python policy/config objects and yearly policy signals
- `src/natm/core/agents.py`: Mesa operator agents for aviation and maritime firms
- `src/natm/core/model.py`: Mesa `Model`, AgentSet activation, and DataCollector output
- `src/natm/cli.py`: command-line entry point
- `config/default.yaml`: baseline scenario

## What The Model Now Captures

- Carbon-price ramp shared across sectors
- Aviation and maritime clean-fuel subsidies
- Sector-specific alternative-fuel adoption mandates
- Infrastructure buildout and learning effects
- Yearly transition pressure and effective cost outputs
- Mesa-native activation through `model.agents_by_type[...] .shuffle_do("step")`
- Mesa-native model and agent reporting through `mesa.DataCollector`
- Multiple operator agents per sector with heterogeneous fleet sizes and costs

## Near-Term Next Steps

1. Replace the starter heuristics with calibrated aviation and maritime data.
2. Split operator agents further into fleet, route, or vessel-level Mesa agents.
3. Add energy pathways, emissions accounting, and richer reporting outputs.
