# Risk-Attitudes Comparison

Synthetic aviation-passenger case for comparing the ambiguity-aware investment
logic across three German airlines. Each airline owns one short-haul aircraft:

- `German Risk Neutral Air`: `decision_attitude=risk_neutral`
- `German Risk Averse Air`: `decision_attitude=risk_averse`
- `German Ambiguity Air`: `decision_attitude=ambiguity_averse`

All three use `investment_logic=ambiguity_aware_utility`. The scenario horizon
runs from 2025 through 2040 and evaluates three future states:

- `baseline`
- `high_fuel_price`
- `delayed_infrastructure`

Run the case with:

```powershell
python run.py --example risk-attitudes-comparison
```

Or run the case directly:

```powershell
natm --case risk-attitudes-comparison --details-dir simulation_results/risk_attitudes
```

Then compare `aviation_robust_frontier.csv`, `agents.csv`, and the robust
frontier view in:

```powershell
solara run dashboard_examples/common_case_dashboard.py
```
