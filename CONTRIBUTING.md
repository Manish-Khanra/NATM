# Contributing to NATM

Thank you for your interest in improving NATM.

NATM is under active development as an open-source technology-transition
diffusion model for aviation and maritime transport systems. Contributions are
welcome through issues, discussions, documentation improvements, data-cleaning
helpers, tests, dashboards, and model extensions.

## Development Setup

```powershell
git clone https://github.com/Manish-Khanra/NATM.git
cd NATM
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pre-commit install
```

Optional extras:

```powershell
python -m pip install -e .[dashboard]
python -m pip install -e .[openap]
```

## Before Submitting Changes

Run:

```powershell
pre-commit run --all-files
pytest
```

For dashboard changes, also launch the relevant dashboard manually:

```powershell
solara run dashboard_examples/aviation_passenger_baseline_dashboard.py
```

## Contribution Guidelines

- Keep aviation, maritime, preprocessing, dashboard, and documentation concerns separated.
- Keep observed stock/activity data out of scenario and technology catalog assumptions.
- Preserve case-file compatibility where possible.
- Add or update tests for behavior changes.
- Document new input variables, outputs, or workflow changes.
- Respect licenses and citation requirements of third-party datasets and dependencies.

## License

By contributing, you agree that your contribution will be licensed under the
GNU General Public License, version 3 only, as used by this repository.
