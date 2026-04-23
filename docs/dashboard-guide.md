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

Important note on energy units:

- the model stores raw energy internally in `kWh`
- the dashboard converts displayed energy values to `TWh`

## 8. Typical Workflow

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

### Switch to saved results

In the browser:

- `Dashboard Source` -> `Saved results`
- choose the run folder from the dropdown

## 9. Current Design

All four dashboard entrypoints use the shared helper:

- `dashboard_examples/common_case_dashboard.py`

This file provides:

- common live/saved-results switching
- shared chart structure
- shared results-folder loading
- shared formatting for energy and investment charts
