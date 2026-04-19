# NATM

NATM stands for NavAero Transition Model.

This repository contains the first development scaffold for a joint aviation and
maritime transition model. The starter version focuses on a simple scenario
loader, a lightweight transition simulation, and a command-line entry point we
can grow into a fuller agent-based model.

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
- `src/natm/core/agents.py`: sector transition logic
- `src/natm/core/model.py`: simulation runner and tabular output
- `src/natm/cli.py`: command-line entry point
- `config/default.yaml`: baseline scenario

## Near-Term Next Steps

1. Replace the starter heuristics with calibrated aviation and maritime data.
2. Expand the sector agents into richer firm, fleet, or route-level entities.
3. Add policy levers, energy pathways, and reporting outputs.
