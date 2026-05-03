# Maritime Cargo Scenario CSV Reference

This document explains the structure of
`data/<case-name>/maritime_scenario.csv` for the current NATM
maritime-cargo implementation.

Use this file when preparing or checking maritime-cargo case inputs.

## CSV Shape

The maritime-cargo scenario table is a wide CSV with one row per scenario
variable and one column per simulation year.

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
demand,freight_tonne_km_demand,Germany,,deepsea,,,,,tkm_per_year,2680000000,2730000000,2780000000
market,operator_market_share,Germany,Hapag-Lloyd,deepsea,,,,,share,1.0,1.0,1.0
operations,load_factor,,Hapag-Lloyd,,,,,,share,0.74,0.74,0.75
```

## How Scope Matching Works

NATM resolves scenario values using `variable_name + year + scope`.

Important rules:

- Blank scope cells mean "generic" and can match any request.
- More specific rows win over less specific rows.
- `variable_group` and `unit` are stored for readability and data management.
  They are not currently part of the lookup key.
- `scenario_id` selects the future scenario for ambiguity-aware decisions. If a
  requested scenario has no matching rows, NATM falls back to `baseline`.

So if both of these exist:

- `technology_availability` for `segment=deepsea`
- `technology_availability` for `segment=deepsea, technology_name=ammonia_deepsea`

then the second row is used when the model asks for `ammonia_deepsea` in the
`deepsea` segment.

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

Fleet stock can keep using
`investment_logic=legacy_weighted_utility_maritime_cargo`. To use the
ambiguity-aware maritime cargo rule, set:

```csv
investment_logic,decision_attitude
ambiguity_aware_utility_maritime_cargo,ambiguity_averse
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

Current groups used by the baseline maritime-cargo case:

- `price`
- `policy`
- `availability`
- `demand`
- `market`
- `operations`
- `delivery`

## Core Maritime Cargo Variables

The current maritime-cargo implementation is centered on:

1. fuel and carbon-price inputs
2. technology and infrastructure availability
3. yearly `tkm` demand
4. operator market-share allocation
5. optional planned deliveries

### Required capacity-planning variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `freight_tonne_km_demand` | Total yearly cargo demand allocated later to operators. | `demand` | `country`, `segment` | none | `unit=tkm_per_year` |
| `operator_market_share` | Fixed share of segment demand allocated to a shipline. | `market` | `country`, `operator_name`, `segment` | none | `unit=share` |

Without these, maritime-cargo growth planning cannot allocate demand correctly.

## Price Variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `primary_energy_price` | Price of the main energy carrier used by a technology. | `price` | `country`, `primary_energy_carrier` | `segment`, `technology_name` | `unit=eur_per_kwh` |
| `secondary_energy_price` | Price of a secondary energy carrier, typically for biofuel co-use. | `price` | `country`, `secondary_energy_carrier` | `segment`, `technology_name`, `saf_pathway` | `unit=eur_per_kwh` |
| `tertiary_energy_price` | Extra compatibility path for biofuel-style branches. | `price` | `country`, `secondary_energy_carrier` | `segment`, `technology_name`, `saf_pathway` | `unit=eur_per_kwh` |
| `carbon_tax` | Carbon cost applied to chargeable emissions. | `policy` | none | `country`, `operator_name` | `unit=eur_per_tco2` |

## Policy Variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `clean_fuel_subsidy` | Subsidy applied to alternative-fuel operating economics. | `policy` | none | `country`, `operator_name`, `segment` | `unit=share` |
| `biofuel_mandate` | Required share of biofuel-type secondary energy use. | `policy` | none | `country`, `segment`, `secondary_energy_carrier`, `saf_pathway` | `unit=share` |
| `ets_allocation_factor` | Share of free ETS-like allocation phased out over time. | `policy` | `operator_name` | `country` | `unit=share` |
| `reported_emission` | Share of total emissions treated as reported for the current framework branch logic. | `policy` | `operator_name` | `country`, `segment` | `unit=share` |

## Availability Variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `technology_availability` | Whether a technology can be selected in a year. | `availability` | `technology_name` | `country`, `operator_name`, `segment` | `unit=flag` |
| `infrastructure_availability` | Whether the required fueling or bunkering infrastructure is available. | `availability` | `country`, `technology_name` | `operator_name`, `segment` | `unit=flag` |
| `biofuel_availability` | Whether a biofuel pathway is available for the selected branch. | `availability` | `country`, `technology_name`, `secondary_energy_carrier`, `saf_pathway` | `operator_name`, `segment` | `unit=flag` |

## Operational Variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `load_factor` | Share of vessel freight capacity used in annual operations. | `operations` | `operator_name` | `country`, `segment` | `unit=share` |
| `freight_rate` | Revenue rate used in cargo earnings calculations. | `operations` | `operator_name` | `country`, `segment` | `unit=eur_per_tonne_km` |

## Delivery Variables

| Variable name | Meaning | Recommended `variable_group` | Required scope columns | Optional scope columns | Required non-scope columns |
|---|---|---|---|---|---|
| `planned_delivery_count` | Number of planned vessel additions applied before endogenous growth. | `delivery` | `country`, `operator_name`, `segment` | `technology_name` | `unit=count` |

## What The Current Maritime Cargo Framework Uses

The current NATM maritime-cargo framework uses:

- `maritime_fleet_stock.csv` for shipline-owned vessel stock
- `maritime_technology_catalog.csv` for vessel technologies, fuels, and emission factors
- `maritime_scenario.csv` for yearly prices, policy, availability, demand, and delivery assumptions

Within the model, maritime-cargo growth is demand-driven:

1. read yearly `freight_tonne_km_demand`
2. allocate it by `operator_market_share`
3. compute current fleet carrying capacity
4. apply `planned_delivery_count` first if present
5. add endogenous vessels only if a residual `tkm` gap remains

So this scenario file is not only policy input; it also drives the yearly cargo
market context used by shipline agents.
