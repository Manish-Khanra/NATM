# Investment Logic Guide

This guide shows how to configure `investment_logic` and `decision_attitude`
for legacy, risk-neutral, risk-averse, and ambiguity-averse simulations. The
same public strategy names apply to all four model types:

- aviation passenger
- aviation cargo
- maritime passenger
- maritime cargo

## Fleet Stock Columns

Use `legacy_weighted_utility` when you want the existing weighted-utility
behavior:

```csv
investment_logic,decision_attitude
legacy_weighted_utility,risk_neutral
```

Use `ambiguity_aware_utility` when candidate technologies should be evaluated
over a configured set of future scenarios:

```csv
investment_logic,decision_attitude
ambiguity_aware_utility,risk_neutral
ambiguity_aware_utility,risk_averse
ambiguity_aware_utility,ambiguity_averse
```

The allowed `decision_attitude` values are:

- `risk_neutral`: selects the technology with the highest expected utility
- `risk_averse`: selects the technology with the best probability-weighted
  mean utility over the worst alpha probability mass
- `ambiguity_averse`: selects the technology with the best worst-case expected
  shortfall utility under the configured probability ambiguity set

If `decision_attitude` is missing, NATM defaults to `risk_neutral`. The column
only changes behavior for `ambiguity_aware_utility`; legacy weighted-utility
decisions are unchanged.

Older sector-specific investment-logic names remain accepted as aliases for
existing cases, but new input files should use only:

- `legacy_weighted_utility`
- `ambiguity_aware_utility`

## Scenario YAML

Add the ambiguity-aware scenario ensemble to `scenario.yaml`:

```yaml
ambiguity_aware_decision:
  enabled: true
  scenario_ids:
    - baseline
    - high_fuel_price
    - delayed_infrastructure
  probabilities:
    baseline: 0.5
    high_fuel_price: 0.3
    delayed_infrastructure: 0.2
  ambiguity:
    enabled: true
    probability_deviation: 0.1
  expected_shortfall_alpha: 0.2
  robust_metric: worst_case_expected_shortfall
```

`expected_shortfall_alpha: 0.2` means the downside-sensitive criterion uses the
worst 20 percent probability mass. The default ambiguity-averse metric is
`worst_case_expected_shortfall`. To make ambiguity-averse actors use worst-case
mean utility instead, set:

```yaml
robust_metric: worst_case_expected_utility
```

## Scenario CSV

Scenario CSVs can optionally include `scenario_id`. If the column is missing,
all rows are treated as `baseline`. When present, duplicate only the rows that
should differ by scenario.

Example:

```csv
scenario_id,variable_group,variable_name,country,operator_name,segment,technology_name,primary_energy_carrier,secondary_energy_carrier,saf_pathway,unit,2025,2030,2035
baseline,price,primary_energy_price,Germany,,,,kerosene,,,eur_per_kwh,0.082,0.092,0.102
high_fuel_price,price,primary_energy_price,Germany,,,,kerosene,,,eur_per_kwh,0.100,0.145,0.190
baseline,availability,infrastructure_availability,Germany,,short,hydrogen_short,,,,share,0.10,0.55,0.90
delayed_infrastructure,availability,infrastructure_availability,Germany,,short,hydrogen_short,,,,share,0.00,0.15,0.50
```

Good scenario-specific variables include fuel prices, carbon prices,
technology price indices, clean-fuel availability, infrastructure availability,
mandates, and subsidies.

## Workflow

1. Choose or copy a case folder under `data/`.
2. In `aviation_fleet_stock.csv` or `maritime_fleet_stock.csv`, set
   `investment_logic=ambiguity_aware_utility`.
3. Set `decision_attitude` to `risk_neutral`, `risk_averse`, or
   `ambiguity_averse`.
4. Add `ambiguity_aware_decision` to `scenario.yaml`.
5. Add optional `scenario_id` rows to `aviation_scenario.csv` or
   `maritime_scenario.csv`.
6. Run the model:

```powershell
natm --case <case-name> --details-dir simulation_results/<run-name>
```

7. Inspect `aviation_robust_frontier.csv` or `maritime_robust_frontier.csv`.
8. Open the common dashboard to view the robust frontier chart:

```powershell
solara run dashboard_examples/common_case_dashboard.py
```

The robust frontier outputs include `expected_utility`,
`expected_shortfall_utility`, `worst_case_utility`,
`worst_case_expected_shortfall_utility`, `robust_score`, and `selected_flag`.
