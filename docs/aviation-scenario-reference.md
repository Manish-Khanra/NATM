# Aviation Scenario CSV Reference

This document explains the structure of `data/<case-name>/aviation_scenario.csv`
for the current aviation-passenger NATM implementation.

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

Example shape:

```csv
variable_group,variable_name,country,operator_name,segment,technology_name,primary_energy_carrier,secondary_energy_carrier,saf_pathway,unit,2025,2026,2027
policy,carbon_price,,,,,,,,eur_per_tco2,35,45,58
market,passenger_km_demand,Germany,,medium,,,,,passenger_km,1980000000,2010000000,2040000000
market,operator_market_share,Germany,Lufthansa,medium,,,,,share,0.72,0.72,0.72
```

## How Scope Matching Works

NATM resolves scenario values using `variable_name + year + scope`.

Important rules:

- Blank scope cells mean "generic" and can match any request.
- More specific rows win over less specific rows.
- `variable_group` and `unit` are stored for documentation and data management.
  They are not currently part of the lookup key.

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
model.

### Required for capacity planning

These are required by the current aviation-passenger case validation.

| variable_name | Recommended variable_group | Required scope | Notes |
| --- | --- | --- | --- |
| `passenger_km_demand` | `market` | `country`, `segment` | Total annual passenger-km demand for that country and segment. |
| `operator_market_share` | `market` | `country`, `operator_name`, `segment` | Airline share used to allocate country-segment passenger-km demand. |

### Optional planned deliveries

| variable_name | Recommended variable_group | Required scope | Optional scope | Notes |
| --- | --- | --- | --- | --- |
| `planned_delivery_count` | `delivery` | `country`, `operator_name`, `segment` | `technology_name` | Number of aircraft delivered in that year before endogenous growth logic runs. If `technology_name` is provided, the planned delivery is forced to that technology. |

### Prices and policy

| variable_name | Recommended variable_group | Required scope | Optional scope | Notes |
| --- | --- | --- | --- | --- |
| `carbon_price` | `policy` | none | none | Global carbon price for the year. |
| `clean_fuel_subsidy` | `policy` | none | none | Aviation-wide clean fuel subsidy share. |
| `adoption_mandate` | `policy` | none | none | Aviation-wide adoption mandate share. |
| `saf_mandate` | `policy` | none | `secondary_energy_carrier`, `saf_pathway` | SAF mandate share used for drop-in fuels. |
| `ets_allocation_factor` | `policy` | `operator_name` | none | Operator-specific ETS free allocation reduction factor. |
| `primary_energy_price` | `price` | `country`, `primary_energy_carrier` | none | Primary energy price used in annual operating cost. |
| `secondary_energy_price` | `price` | `country`, `secondary_energy_carrier` | `saf_pathway` | Secondary energy price, including SAF and battery cases. |

### Demand and revenue

| variable_name | Recommended variable_group | Required scope | Notes |
| --- | --- | --- | --- |
| `economy_occupancy` | `demand` | `operator_name` | Economy occupancy share. |
| `business_occupancy` | `demand` | `operator_name` | Business occupancy share. |
| `first_occupancy` | `demand` | `operator_name` | First-class occupancy share. |
| `economy_income` | `demand` | `operator_name` | Economy income in the configured `unit`. |
| `business_income` | `demand` | `operator_name` | Business income in the configured `unit`. |
| `first_income` | `demand` | `operator_name` | First-class income in the configured `unit`. |
| `freight_rate` | `demand` | `operator_name` | Freight revenue rate for belly cargo. |

### Technology cost and availability

| variable_name | Recommended variable_group | Required scope | Optional scope | Notes |
| --- | --- | --- | --- | --- |
| `technology_dynamic_price_index` | `cost_index` | `segment`, `technology_name` | none | Dynamic multiplier added to technology capex. |
| `technology_availability` | `availability` | `segment`, `technology_name` | none | Flag indicating whether the technology is commercially available that year. |
| `infrastructure_availability` | `availability` | `country`, `segment`, `technology_name` | none | Flag indicating whether the airport/fuel/infrastructure setup is available. |
| `saf_availability` | `availability` | `country`, `segment`, `technology_name`, `secondary_energy_carrier` | `saf_pathway` | Flag controlling SAF-specific pathway availability. |

### Branch and blend logic

| variable_name | Recommended variable_group | Required scope | Optional scope | Notes |
| --- | --- | --- | --- | --- |
| `secondary_energy_cap_active` | `branch` | `country`, `segment`, `technology_name`, `secondary_energy_carrier` | `saf_pathway` | Flag controlling whether a technology can use its secondary energy stream. |
| `drop_in_mandate_active` | `branch` | `country`, `segment`, `technology_name`, `secondary_energy_carrier` | `saf_pathway` | Flag controlling whether drop-in mandate logic is active. |
| `maximum_secondary_energy_share` | `branch` | `country`, `segment`, `technology_name`, `secondary_energy_carrier` | `saf_pathway` | Max usable secondary energy share for the technology in that scope. |

### Deprecated for aviation growth

| variable_name | Status | Notes |
| --- | --- | --- |
| `market_growth` | Deprecated | The current aviation-passenger growth logic no longer uses this variable. It may remain in old case files for reference only. |

## Practical Guidance

- For variables that should apply everywhere, leave scope columns blank.
- For operator-specific commercial inputs, fill `operator_name` and leave other
  unrelated scope columns blank.
- For technology gates, always scope at least by `segment` and
  `technology_name`.
- For fuel-specific rows, use `primary_energy_carrier` or
  `secondary_energy_carrier` as appropriate.
- For SAF rows, also fill `saf_pathway` when pathway-specific behavior matters.

## Current Baseline Case

The baseline aviation-passenger case in
`data/baseline-transition/aviation_scenario.csv` currently includes examples
for all of the variable families above, including:

- demand allocation through `passenger_km_demand` and `operator_market_share`
- optional growth overrides through `planned_delivery_count`
- policy, price, availability, and branch controls for technology adoption
