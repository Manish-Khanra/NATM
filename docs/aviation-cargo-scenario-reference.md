# Aviation Cargo Scenario CSV Reference

This document explains the structure of
`data/<case-name>/aviation_scenario.csv` for the current NATM
aviation-cargo implementation.

It is the cargo-specific companion to
`docs/aviation-passenger-reference.md`. Use this file when preparing or checking
cargo case inputs.

## CSV Shape

The cargo scenario table is a wide CSV with one row per scenario variable and
one column per simulation year.

Required columns:

- `variable_group`
- `variable_name`
- `country`
- `operator_name`
- `segment`
- `technology_name`
- `primary_energy_carrier`
- `secondary_energy_carrier`
- `saf_pathway`
- `unit`
- one or more year columns such as `2025`, `2026`, `2027`, ...

Optional column:

- `scenario_id`

If `scenario_id` is missing, all rows are treated as `baseline`.

Example shape:

```csv
variable_group,variable_name,country,operator_name,segment,technology_name,primary_energy_carrier,secondary_energy_carrier,saf_pathway,unit,2025,2026,2027
demand,freight_tonne_km_demand,Germany,,long,,,,,tkm_per_year,1950000000,1990000000,2030000000
market,operator_market_share,Germany,Lufthansa Cargo,long,,,,,share,1.0,1.0,1.0
operations,freight_rate,,Lufthansa Cargo,,,,,,eur_per_tonne_km,0.145,0.146,0.147
```

## How Scope Matching Works

NATM resolves scenario values using `variable_name + year + scope`.

Important rules:

- Blank scope cells mean "generic" and can match any request.
- More specific rows win over less specific rows.
- `variable_group` and `unit` are kept for data management and readability.
  They are not currently part of the lookup key.
- `scenario_id` selects the future scenario for ambiguity-aware decisions. If a
  requested scenario has no matching rows, NATM falls back to `baseline`.

So if both of these exist:

- `technology_availability` for `segment=long`
- `technology_availability` for `segment=long, technology_name=hydrogen_freight_long`

then the second row is used when the model asks for
`hydrogen_freight_long` in the `long` segment.

## Scope Columns

Available scope columns are:

- `country`
- `operator_name`
- `segment`
- `technology_name`
- `primary_energy_carrier`
- `secondary_energy_carrier`
- `saf_pathway`

Use only the columns that matter for the variable. Leave the others blank.

## Ambiguity-Aware Decision Inputs

Fleet stock can keep using `investment_logic=legacy_weighted_utility_cargo`.
To use the ambiguity-aware cargo rule, set:

```csv
investment_logic,decision_attitude
ambiguity_aware_utility_cargo,risk_averse
```

Allowed `decision_attitude` values are `risk_neutral`, `risk_averse`, and
`ambiguity_averse`. Missing values default to `risk_neutral`; the column does
not change legacy weighted-utility behavior.

Configure the scenario set in `scenario.yaml`:

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
  robust_metric: worst_case_expected_utility
```

This is an ambiguity-aware extension of the existing utility-based fleet
diffusion model. Candidate technologies are evaluated over the configured
future scenarios. Risk-neutral actors maximise expected utility, risk-averse
actors use downside-sensitive expected shortfall, and ambiguity-averse actors
use worst-case probability-weighted criteria over a bounded ambiguity set.

## Variable Groups

`variable_group` is a human-readable grouping field. It helps keep the CSV
organized and should be used consistently, but the current code does not depend
on it for lookups.

Current groups used by the baseline cargo case:

- `price`
- `policy`
- `availability`
- `branch`
- `demand`
- `market`
- `operations`
- `delivery`
- `cost_index`

## Supported Cargo Variable Names

### Column meaning in the tables below

- `Definition`: what the variable means in the model
- `Required scope columns`: scope columns that should be filled for a correct row
- `Optional scope columns`: extra columns you may fill when you want a more
  specific row to override a generic one
- `Other required columns`: additional non-scope columns that must still be
  filled correctly, usually `variable_group` and `unit`

### Required for cargo capacity planning

These are required by the current aviation-cargo case validation.

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `freight_tonne_km_demand` | Total annual freight demand that must be served in a given country and segment, expressed as yearly tonne-kilometers. | `demand` | `country`, `segment` | none | `unit` should be `tkm_per_year` |
| `operator_market_share` | Fixed airline share used to allocate country-segment cargo demand to an operator. | `market` | `country`, `operator_name`, `segment` | none | `unit` should be `share` |

### Optional planned deliveries

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `planned_delivery_count` | Number of cargo aircraft delivered in that year before endogenous growth logic runs. | `delivery` | `country`, `operator_name`, `segment` | `technology_name` | `unit` should be `count` |

### Prices and policy

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `carbon_price` | Global carbon price applied to chargeable emissions. | `policy` | none | none | `unit` should describe carbon price |
| `clean_fuel_subsidy` | Aviation-wide subsidy share applied to alternative clean-fuel energy costs. | `policy` | none | none | `unit` should be `share` |
| `adoption_mandate` | Aviation-wide adoption or mandate pressure used in the transition logic. | `policy` | none | none | `unit` should be `share` |
| `saf_mandate` | SAF blending mandate used for drop-in fuel logic. | `policy` | none | `secondary_energy_carrier`, `saf_pathway` | `unit` should be `share` |
| `ets_allocation_factor` | Operator-specific factor controlling the reduction of free ETS allocation. | `policy` | `operator_name` | none | `unit` should be `share` |
| `primary_energy_price` | Price of the primary energy carrier used by a technology. | `price` | `country`, `primary_energy_carrier` | none | `unit` should describe the energy price basis |
| `secondary_energy_price` | Price of the secondary energy carrier used by a technology. | `price` | `country`, `secondary_energy_carrier` | `saf_pathway` | `unit` should describe the energy price basis |

### Cargo demand and revenue

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `load_factor` | Cargo load factor used in freight tonne-km capacity and annual revenue calculations. | `operations` | `operator_name` | none | `unit` should be `share` |
| `freight_rate` | Cargo revenue rate used in annual revenue calculations. | `operations` | `operator_name` | none | `unit` should describe the freight-rate basis, such as `eur_per_tonne_km` |

### Technology cost and availability

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `technology_dynamic_price_index` | Dynamic multiplier added to the base technology capex for a given year. | `cost_index` | `technology_name` | `segment` | `unit` should be `share` |
| `technology_availability` | Commercial availability flag for a technology in that year. | `availability` | `technology_name` | `segment` | `unit` should indicate a flag |
| `infrastructure_availability` | Availability flag for the required airport, fuel, or infrastructure setup. | `availability` | `country`, `technology_name` | `segment` | `unit` should indicate a flag |
| `saf_availability` | Availability flag for a specific SAF-enabled technology or pathway. | `availability` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |

### Branch and blend logic

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `secondary_energy_cap_active` | Flag controlling whether a technology can use its configured secondary energy stream. | `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
| `drop_in_mandate_active` | Flag controlling whether drop-in mandate logic is active for that technology or pathway scope. | `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
| `maximum_secondary_energy_share` | Maximum usable secondary-energy share for a technology in that scope. | `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should be `share` |

## Practical Guidance

- For variables that should apply everywhere, leave scope columns blank.
- For operator-specific commercial inputs, fill `operator_name` and leave other
  unrelated scope columns blank.
- `technology_name` is the technology identity. Use `segment` only when the
  scenario value differs by operating segment.
- For fuel-specific rows, use `primary_energy_carrier` or
  `secondary_energy_carrier` as appropriate.
- For SAF rows, also fill `saf_pathway` when pathway-specific behavior matters.
- Use `freight_tonne_km_demand` as the yearly cargo growth driver instead of any
  percentage-based market-growth variable.

## Current Baseline Cargo Case

The baseline aviation-cargo case in
`data/baseline-cargo-transition/aviation_scenario.csv` includes examples
for the cargo variable families above, including:

- demand allocation through `freight_tonne_km_demand` and `operator_market_share`
- yearly cargo assumptions through `load_factor` and `freight_rate`
- optional planned deliveries through `planned_delivery_count`
- policy, price, availability, and branch controls for technology adoption
