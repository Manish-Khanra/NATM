# Investment Logic Guide

This guide shows the canonical `investment_logic`, `decision_attitude`, and
`decision_mode` settings for NATM. The same public strategy names apply to
all four model types:

- aviation passenger
- aviation cargo
- maritime passenger
- maritime cargo

## Fleet Stock Columns

Use `legacy_weighted_utility` when you want the existing deterministic
weighted-utility behaviour:

```csv
investment_logic,decision_attitude
legacy_weighted_utility,risk_neutral
```

Use `ambiguity_aware_utility` when candidate technologies should be evaluated
across scenario-specific NPVs and belief-set probabilities:

```csv
investment_logic,decision_attitude
ambiguity_aware_utility,risk_neutral
ambiguity_aware_utility,risk_averse_mean
ambiguity_aware_utility,risk_averse_expected_shortfall
```

### `decision_attitude` vs. `decision_mode`

For `ambiguity_aware_utility`, NATM keeps two independent fleet-stock columns,
the same way AURIS keeps `decision_attitude` and `decision_mode` separate in
`plants.csv`:

- `decision_mode` is the precise NPV-selection rule that actually drives the
  math: `risk_neutral`, `risk_averse_mean`, or `risk_averse_expected_shortfall`.
  When set, it is authoritative.
- `decision_attitude` is a coarser, human-readable behavioral label:
  `risk_neutral`, `risk_averse`, or `ambiguity_averse` (the precise mode names
  are also accepted directly, for backward compatibility). When `decision_mode`
  is blank, NATM derives it from `decision_attitude`:
  - `risk_neutral` -> `risk_neutral`
  - `risk_averse_mean` / `risk_averse_expected_shortfall` -> itself, unchanged
  - `risk_averse` -> `risk_averse_expected_shortfall`
  - `ambiguity_averse` -> `risk_averse_expected_shortfall`

The label does not have to match the rule it defaults to. Two cases can use
the same `decision_attitude` label with different `decision_mode` values to
tell different stories about the same underlying math, or the same math under
different narrative labels:

```csv
investment_logic,decision_attitude,decision_mode
ambiguity_aware_utility,ambiguity_averse,risk_averse_mean
ambiguity_aware_utility,risk_averse,risk_averse_mean
ambiguity_aware_utility,risk_averse,risk_averse_expected_shortfall
```

What each `decision_mode` value selects:

- `risk_neutral`: selects the highest expected NPV using a representative
  probability vector. By default this is the mean probability across all belief
  sets.
- `risk_averse_mean`: selects the highest robust worst-case mean NPV. NATM
  converts NPV to loss with `loss = -NPV`, finds the admissible probability
  vector that maximises expected loss, and converts the result back to NPV.
- `risk_averse_expected_shortfall`: selects the highest robust
  expected-shortfall NPV. NATM again works on the loss scale and evaluates the
  worst tail under the most adverse admissible probability vector.

If both columns are missing, NATM defaults to `decision_attitude=risk_neutral`,
which resolves to `decision_mode=risk_neutral`. Neither column changes
behaviour for `legacy_weighted_utility`; only `ambiguity_aware_utility` reads
them. The resolved mode is re-derived fresh every time a decision is scored
(never cached), and is visible per decision in `ambiguity_decision_scores.csv`
and per aircraft/vessel/year in `aircraft.csv` and `agents.csv`.

Older sector-specific investment-logic names remain accepted as aliases for
existing cases, but new input files should use only:

- `legacy_weighted_utility`
- `ambiguity_aware_utility`

## Scenario YAML

For `ambiguity_aware_utility`, add an `ambiguity_aware_decision` block with a
belief-set probability table. The table is mandatory for the NPV-based
ambiguity-aware strategy.

```yaml
ambiguity_aware_decision:
  enabled: true
  scenario_ids:
    - baseline
    - high_fuel_price
    - delayed_infrastructure
  probability_table: ambiguity_probabilities.csv
  tail_alpha: 0.95
```

`tail_alpha` is the confidence level for
`risk_averse_expected_shortfall`. For example, `tail_alpha: 0.95` means the
worst 5 percent tail.

By default, risk-neutral actors use the mean scenario probability across all
belief sets:

```text
p_mean[s] = mean_b p[s,b]
```

To make risk-neutral actors use one named belief set instead, add:

```yaml
risk_neutral_belief_set: Base
```

`ambiguity_aware_decision.risk_metric` is deprecated as an active selector.
Selection is controlled by the fleet-stock `decision_mode` value, or
`decision_attitude` when `decision_mode` is blank.

## Belief-Set Probability Table

The probability table contains several plausible belief sets over the same
scenario space. NATM validates every belief set and constructs probability
bounds:

```text
p_lower[s] = min_b p[s,b]
p_upper[s] = max_b p[s,b]
Q = {q: p_lower[s] <= q[s] <= p_upper[s], sum_s q[s] = 1}
```

Wide probability table example:

```csv
scenario,Base,Electricity_based,Hydrogen_based,Conservative
baseline,0.40,0.25,0.35,0.55
high_fuel_price,0.35,0.50,0.25,0.25
delayed_infrastructure,0.25,0.25,0.40,0.20
```

Long probability table example:

```csv
scenario,belief_set,probability
baseline,Base,0.40
high_fuel_price,Base,0.35
delayed_infrastructure,Base,0.25
baseline,Electricity_based,0.25
high_fuel_price,Electricity_based,0.50
delayed_infrastructure,Electricity_based,0.25
```

Every belief set must cover the same scenarios, each belief-set probability
must be numeric and between 0 and 1, and each belief set must sum to 1.

## Decision Metrics

For every candidate technology `d` and scenario `s`, NATM evaluates scenario
NPV:

```text
NPV[d,s]
```

Risk-neutral mode uses expected NPV directly:

```text
expected_npv[d] = sum_s p_mean[s] * NPV[d,s]
selected = argmax_d expected_npv[d]
```

Risk-averse mean mode converts NPV to loss and evaluates the worst admissible
mean loss:

```text
loss[d,s] = -NPV[d,s]
robust_mean_loss[d] = max_q sum_s q[s] * loss[d,s]
robust_worst_case_mean_npv[d] = -robust_mean_loss[d]
selected = argmax_d robust_worst_case_mean_npv[d]
```

Risk-averse expected-shortfall mode also works on the loss scale:

```text
robust_es_loss[d] = max_q ES_alpha(loss[d,.], q)
robust_expected_shortfall_npv[d] = -robust_es_loss[d]
selected = argmax_d robust_expected_shortfall_npv[d]
```

On the NPV scale, higher is better. On the loss scale, lower is better. NATM
does not select the highest single-scenario NPV.

`robust_es_loss` is solved as a single joint linear program over both the
adverse probability vector `q` and the CVaR tail-weight vector `w` (via
`scipy.optimize.linprog`), rather than reusing the probability vector that
maximizes worst-case mean loss:

```text
maximize   w . loss
subject to q in [p_lower, p_upper], sum(q) = 1
           w >= 0, sum(w) = 1
           beta * w <= q   (elementwise, beta = 1 - tail_alpha)
```

`robust_mean_loss` keeps its own simpler closed-form solver: for interval
probability bounds, the adverse mean-loss vector is the extreme point that
greedily assigns as much probability as bounds allow to the highest-loss
scenarios in order.

If a candidate has missing or infeasible NPV in any required scenario, it is
excluded from robust selection for that decision context and recorded in
`ambiguity_excluded_candidates.csv`. Missing NPV is never filled with zero.

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

## Outputs

When `ambiguity_aware_utility` runs, NATM writes:

- `ambiguity_probability_bounds.csv`
- `ambiguity_decision_scores.csv`
- `ambiguity_worst_case_probabilities.csv`
- `selected_ambiguity_aware_decisions.csv`
- `ambiguity_excluded_candidates.csv` when candidates are excluded
- `aviation_robust_frontier.csv` or `maritime_robust_frontier.csv`

The NPV score outputs include:

- `decision_mode`
- `expected_npv`
- `robust_mean_loss`
- `robust_worst_case_mean_npv`
- `robust_es_loss`
- `robust_expected_shortfall_npv`
- `selected`
- `rank`

The probability-vector output records the representative risk-neutral vector,
the worst-case vector for `risk_averse_mean`, and the worst-case vector plus
tail weights for `risk_averse_expected_shortfall`.

## Dynamic Investment Timing (Aviation Passenger, Opt-In)

These features currently apply only to `AviationPassengerAirlineAgent` (both
`legacy_weighted_utility` and `ambiguity_aware_utility`). They default to
today's behavior; a case must opt in through a new `investment_timing` block
in `scenario.yaml`:

```yaml
investment_timing:
  include_continue_option: false        # set true to enable continue-vs-invest
  residual_value_method: none           # or straight_line_remaining_life
```

### Continue vs. invest

By default, once an aircraft is due for replacement it is always re-invested
into. With `include_continue_option: true`, NATM adds one more candidate to
the ranking each time a replacement is being evaluated: keep flying the
current aircraft, at zero capex, for its already-scheduled remaining
lifetime. This only ever changes anything when an aircraft is pulled into
replacement early by the policy/subsidy acceleration window while its
current technology is still economically or environmentally competitive
against the catalog alternatives; aircraft at natural end of life always get
replaced. The chosen action is recorded per aircraft/year in the new
`action` column (`invest`, `continue_current`, or `planned_investment`) in
`aircraft.csv` and, for `ambiguity_aware_utility`, in
`aviation_robust_frontier.csv`.

### Planned investments

Fleet stock can force a specific aircraft to a specific technology in a
specific year, independent of whether it is naturally due, using numbered
columns in `aviation_fleet_stock.csv`:

```csv
aircraft_id,planned_investment_1_year,planned_investment_1_technology_name,planned_investment_1_technology_pattern
353,2030,drop_in_saf_medium,
1241,2032,,hybrid_electric_*
```

Add `_2_`, `_3_`, and so on for later events on the same aircraft. Give
either an exact `technology_name` or a shell-style `technology_pattern`
(matched with `fnmatch` against the catalog); when a pattern matches several
technologies, the aircraft's normal ranking (utility or robust NPV) selects
among that family. Every planned-investment technology reference is
validated against the technology catalog when the case loads, so a typo
fails at startup rather than mid-run.

### Residual value

By default, NPV is projected over a technology's full nominal
`lifetime_years` even when that runs past `scenario.end_year`. Setting
`residual_value_method: straight_line_remaining_life` instead truncates the
projection at the model horizon and credits back the unused CAPEX life:

```text
residual_value = capex * (lifetime_years - evaluated_years) / lifetime_years
```

discounted back at the technology's own `payback_interest_rate`. This only
changes anything for a case whose `scenario.end_year` is shorter than a
winning technology's `lifetime_years`; it never applies to `continue_current`
candidates, since those spend no fresh capex to credit back.

## Workflow

1. Choose or copy a case folder under `data/`.
2. In `aviation_fleet_stock.csv` or `maritime_fleet_stock.csv`, set
   `investment_logic=ambiguity_aware_utility`.
3. Set `decision_mode` to `risk_neutral`, `risk_averse_mean`, or
   `risk_averse_expected_shortfall` (or leave it blank and set `decision_attitude`
   to `risk_neutral`, `risk_averse`, or `ambiguity_averse` instead).
4. Add `ambiguity_aware_decision.probability_table` to `scenario.yaml`.
5. Add `scenario_id` rows to `aviation_scenario.csv` or `maritime_scenario.csv`
   when scenario values differ.
6. Run the model:

```powershell
natm --case <case-name> --details-dir simulation_results/<run-name>
```

7. Inspect `ambiguity_decision_scores.csv`,
   `selected_ambiguity_aware_decisions.csv`, and the sector robust frontier
   output.
8. Open the common dashboard to view robust frontier and loss diagnostics:

```powershell
solara run dashboard_examples/common_case_dashboard.py
```
