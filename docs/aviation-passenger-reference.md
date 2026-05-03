# Aviation Scenario CSV Reference

This document explains the structure of `data/<case-name>/aviation_scenario.csv`
for the current NATM aviation-passenger implementation. For the cargo-only companion, see
`docs/aviation-cargo-scenario-reference.md`.

## CSV Shape

The scenario table is a wide CSV with one row per scenario variable and one
column per simulation year.

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
policy,carbon_price,,,,,,,,eur_per_tco2,35,45,58
market,passenger_km_demand,Germany,,medium,,,,,passenger_km,1980000000,2010000000,2040000000
market,operator_market_share,Germany,Lufthansa,medium,,,,,share,0.72,0.72,0.72
```

Cargo cases follow the same structure, but use cargo-specific variables such as
`freight_tonne_km_demand` with a yearly unit like `tkm_per_year`.

## How Scope Matching Works

NATM resolves scenario values using `variable_name + year + scope`.

Important rules:

- Blank scope cells mean "generic" and can match any request.
- More specific rows win over less specific rows.
- `variable_group` and `unit` are stored for documentation and data management.
  They are not currently part of the lookup key.
- `scenario_id` selects the future scenario for ambiguity-aware decisions. If a
  requested scenario has no matching rows, NATM falls back to `baseline`.

So if both of these exist:

- `technology_availability` for `segment=long`
- `technology_availability` for `segment=long, technology_name=hydrogen_long`

then the second row is used when the model asks for `hydrogen_long` in the
`long` segment.

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

Fleet stock can keep using `investment_logic=legacy_weighted_utility`. To use
the ambiguity-aware passenger rule, set:

```csv
investment_logic,decision_attitude
ambiguity_aware_utility,risk_neutral
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

Current groups used by the baseline case:

- `price`
- `policy`
- `availability`
- `branch`
- `demand`
- `market`
- `delivery`
- `cost_index`

## Supported Variable Names

This list reflects the variables currently read by the NATM aviation-passenger
and aviation-cargo models.

### Column meaning in the tables below

- `Definition`: what the variable means in the model
- `Required scope columns`: scope columns that should be filled for a correct row
- `Optional scope columns`: extra columns you may fill when you want a more
  specific row to override a generic one
- `Other required columns`: additional non-scope columns that must still be
  filled correctly, usually `variable_group` and `unit`

### Required for passenger capacity planning

These are required by the current aviation-passenger case validation.

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `passenger_km_demand` | Total annual passenger-km demand that must be served in a given country and segment. | `market` | `country`, `segment` | none | `unit` should describe passenger-km |
| `operator_market_share` | Fixed airline share used to allocate country-segment passenger-km demand to an operator. | `market` | `country`, `operator_name`, `segment` | none | `unit` should be `share` |

### Required for cargo capacity planning

These are required by the current aviation-cargo case validation.

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `freight_tonne_km_demand` | Total annual freight demand that must be served in a given country and segment, expressed as yearly tonne-kilometers. | `demand` | `country`, `segment` | none | `unit` should be `tkm_per_year` |
| `operator_market_share` | Fixed airline share used to allocate country-segment cargo demand to an operator. | `market` | `country`, `operator_name`, `segment` | none | `unit` should be `share` |

### Optional planned deliveries

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `planned_delivery_count` | Number of aircraft delivered in that year before endogenous growth logic runs. | `delivery` | `country`, `operator_name`, `segment` | `technology_name` | `unit` should be `aircraft_count` |

### Prices and policy

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `carbon_price` | Global carbon price applied to chargeable emissions. | `policy` | none | none | `unit` should describe carbon price |
| `clean_fuel_subsidy` | Aviation-wide subsidy share applied to alternative clean-fuel energy costs. | `policy` | none | none | `unit` should be `share` |
| `adoption_mandate` | Aviation-wide adoption or mandate pressure used in the transition logic. | `policy` | none | none | `unit` should be `share` |
| `saf_mandate` | SAF blending mandate used for drop-in fuel logic. | `policy` | none | `secondary_energy_carrier`, `saf_pathway` | `unit` should be `share` |
| `ets_allocation_factor` | Operator-specific factor controlling the reduction of free ETS allocation. | `policy` | `operator_name` | none | `unit` should be `share` |
| `primary_energy_price` | Price of the primary energy carrier used by a technology. | `price` | `country`, `primary_energy_carrier` | none | `unit` should describe the energy price basis |
| `secondary_energy_price` | Price of the secondary energy carrier used by a technology, including SAF and battery cases. | `price` | `country`, `secondary_energy_carrier` | `saf_pathway` | `unit` should describe the energy price basis |

### Demand and revenue

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `economy_occupancy` | Economy-class occupancy share used in revenue and effective load factor calculations. | `demand` | `operator_name` | none | `unit` should be `share` |
| `business_occupancy` | Business-class occupancy share used in revenue and effective load factor calculations. | `demand` | `operator_name` | none | `unit` should be `share` |
| `first_occupancy` | First-class occupancy share used in revenue and effective load factor calculations. | `demand` | `operator_name` | none | `unit` should be `share` |
| `economy_income` | Economy passenger income or yield input used in annual revenue. | `demand` | `operator_name` | none | `unit` should describe the income basis |
| `business_income` | Business passenger income or yield input used in annual revenue. | `demand` | `operator_name` | none | `unit` should describe the income basis |
| `first_income` | First-class passenger income or yield input used in annual revenue. | `demand` | `operator_name` | none | `unit` should describe the income basis |
| `freight_rate` | Belly cargo revenue rate used in annual revenue. | `demand` | `operator_name` | none | `unit` should describe the freight-rate basis |
| `load_factor` | Cargo load factor used in freight tonne-km capacity and annual revenue calculations. | `operations` | `operator_name` | none | `unit` should be `share` |

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
| `drop_in_mandate_active` | Flag controlling whether drop-in mandate logic is active for that technology/pathway scope. | `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
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

## Current Baseline Case

The baseline aviation-passenger case in
`data/baseline-transition/aviation_scenario.csv` currently includes examples
for the passenger variable families above, including:

- demand allocation through `passenger_km_demand` and `operator_market_share`
- optional growth overrides through `planned_delivery_count`
- policy, price, availability, and branch controls for technology adoption

The baseline aviation-cargo case in
`data/baseline-cargo-transition/aviation_scenario.csv` includes cargo
examples such as:

- demand allocation through `freight_tonne_km_demand` and `operator_market_share`
- yearly freight assumptions through `load_factor` and `freight_rate`
- optional planned deliveries through `planned_delivery_count`

Removed from the active baseline case:

- `market_growth`
  The current aviation-passenger model no longer uses it for fleet expansion.
