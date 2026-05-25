# Risk-Attitudes Comparison

Synthetic aviation-passenger case for comparing the ambiguity-aware investment
logic across three German airlines. Each airline owns one short-haul aircraft:

- `German Risk Neutral Air`: `decision_attitude=risk_neutral`
- `German Risk Averse Air`: `decision_attitude=risk_averse_mean`
- `German Ambiguity Air`: `decision_attitude=risk_averse_expected_shortfall`

All three use `investment_logic=ambiguity_aware_utility`. The scenario horizon
runs from 2025 through 2040 and evaluates three future states:

- `baseline`
- `high_fuel_price`
- `delayed_infrastructure`

The case also includes `ambiguity_probabilities.csv`, which defines four
belief sets over those same scenarios:

- `Base`
- `Electricity_based`
- `Hydrogen_based`
- `Conservative`

All three airlines use these belief sets through the NPV-based ambiguity-aware
mode configured in `scenario.yaml`:

```yaml
probability_table: ambiguity_probabilities.csv
tail_alpha: 0.80
```

Run the case with:

```powershell
python run.py --example risk-attitudes-comparison
```

Or run the case directly:

```powershell
natm --case risk-attitudes-comparison --details-dir simulation_results/risk_attitudes
```

Then compare `aviation_robust_frontier.csv`, `agents.csv`,
`ambiguity_probability_bounds.csv`, `ambiguity_decision_scores.csv`, and the
robust frontier view in:

```powershell
solara run dashboard_examples/common_case_dashboard.py
```
