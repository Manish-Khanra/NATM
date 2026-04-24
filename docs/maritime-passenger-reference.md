# Maritime Passenger Scenario CSV Reference

This document explains the structure of
`data/<case-name>/maritime_scenario.csv` for the current NATM
maritime-passenger implementation.

Use this file when preparing or checking maritime-passenger case inputs.

## CSV Shape

The maritime-passenger scenario table is a wide CSV with one row per scenario
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

Example shape:

```csv
variable_group,variable_name,country,operator_name,segment,technology_name,primary_energy_carrier,secondary_energy_carrier,saf_pathway,unit,2025,2026,2027
demand,passenger_km_demand,Germany,,overnight,,,,,pkm_per_year,860000000,874000000,888000000
market,operator_market_share,Germany,DFDS,overnight,,,,,share,1.0,1.0,1.0
operations,passenger_overnight_cabin_occupancy,,DFDS,overnight,,,,,share,0.69,0.69,0.70
```

## How Scope Matching Works

NATM resolves scenario values using `variable_name + year + scope`.

Important rules:

- Blank scope cells mean "generic" and can match any request.
- More specific rows win over less specific rows.
- `variable_group` and `unit` are stored for data management and readability.
  They are not currently part of the lookup key.

So if both of these exist:

- `technology_availability` for `segment=regional`
- `technology_availability` for `segment=regional, technology_name=hydrogen_regional_passenger`

then the second row is used when the model asks for
`hydrogen_regional_passenger` in the `regional` segment.

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

Current groups used by the baseline maritime-passenger case:

- `price`
- `policy`
- `availability`
- `demand`
- `market`
- `operations`
- `revenue`
- `delivery`

## Supported Maritime Passenger Variable Names

### Column meaning in the tables below

- `Definition`: what the variable means in the model
- `Required scope columns`: scope columns that should be filled for a correct row
- `Optional scope columns`: extra columns you may fill when you want a more
  specific row to override a generic one
- `Other required columns`: additional non-scope columns that must still be
  filled correctly, usually `variable_group` and `unit`

### Required for passenger capacity planning

These are required by the current maritime-passenger case validation.

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `passenger_km_demand` | Total annual passenger-km demand that must be served in a given country and segment. | `demand` | `country`, `segment` | none | `unit` should be `pkm_per_year` |
| `operator_market_share` | Fixed shipline share used to allocate country-segment passenger demand to an operator. | `market` | `country`, `operator_name`, `segment` | none | `unit` should be `share` |

### Optional planned deliveries

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `planned_delivery_count` | Number of vessels delivered in that year before endogenous growth logic runs. | `delivery` | `country`, `operator_name`, `segment` | `technology_name` | `unit` should be `count` |

### Prices and policy

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `carbon_tax` | Maritime carbon price used for chargeable emissions. | `policy` | none | none | `unit` should describe carbon price |
| `carbon_price` | Optional alias supported by the model when maritime cases use a shared carbon-price naming convention. | `policy` | none | none | `unit` should describe carbon price |
| `clean_fuel_subsidy` | Maritime-wide subsidy share applied to alternative clean-fuel energy costs. | `policy` | none | none | `unit` should be `share` |
| `biofuel_mandate` | Maritime biofuel blending mandate used for drop-in fuel logic. | `policy` | none | `secondary_energy_carrier`, `saf_pathway` | `unit` should be `share` |
| `adoption_mandate` | Optional alias supported by the model for maritime transition pressure. | `policy` | none | none | `unit` should be `share` |
| `ets_allocation_factor` | Operator-specific factor controlling the reduction of free ETS allocation. | `policy` | `operator_name` | none | `unit` should be `share` |
| `reported_emission` | Share of total emissions that remains reportable or chargeable in policy calculations. | `policy` | `operator_name` | `country`, `segment`, `technology_name` | `unit` should be `share` |
| `primary_energy_price` | Price of the primary energy carrier used by a technology. | `price` | `country`, `primary_energy_carrier` | none | `unit` should describe the energy price basis |
| `secondary_energy_price` | Price of the secondary energy carrier used by a technology. | `price` | `country`, `secondary_energy_carrier` | `saf_pathway` | `unit` should describe the energy price basis |
| `tertiary_energy_price` | Optional tertiary energy price used in some drop-in biofuel branches. | `price` | `country`, `secondary_energy_carrier` | `saf_pathway` | `unit` should describe the energy price basis |

### Occupancy and revenue

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `passenger_economy_class_occupancy` | Occupancy share for the economy-class passenger cabin. | `operations` | `operator_name` | `segment` | `unit` should be `share` |
| `passenger_premium_class_occupancy` | Occupancy share for the premium-class passenger cabin. | `operations` | `operator_name` | `segment` | `unit` should be `share` |
| `passenger_overnight_cabin_occupancy` | Occupancy share for the overnight-cabin passenger cabin. | `operations` | `operator_name` | `segment` | `unit` should be `share` |
| `passenger_business_class_occupancy` | Occupancy share for the business-class passenger cabin. | `operations` | `operator_name` | `segment` | `unit` should be `share` |
| `passenger_family_cabin_occupancy` | Occupancy share for the family-cabin passenger cabin. | `operations` | `operator_name` | `segment` | `unit` should be `share` |
| `passenger_economy_class_ticket_rate` | Ticket-rate input for the economy-class passenger cabin. | `revenue` | `operator_name` | `segment` | `unit` should describe the ticket-rate basis |
| `passenger_premium_class_ticket_rate` | Ticket-rate input for the premium-class passenger cabin. | `revenue` | `operator_name` | `segment` | `unit` should describe the ticket-rate basis |
| `passenger_overnight_cabin_ticket_rate` | Ticket-rate input for the overnight-cabin passenger cabin. | `revenue` | `operator_name` | `segment` | `unit` should describe the ticket-rate basis |
| `passenger_business_class_ticket_rate` | Ticket-rate input for the business-class passenger cabin. | `revenue` | `operator_name` | `segment` | `unit` should describe the ticket-rate basis |
| `passenger_family_cabin_ticket_rate` | Ticket-rate input for the family-cabin passenger cabin. | `revenue` | `operator_name` | `segment` | `unit` should describe the ticket-rate basis |
| `onboard_spending` | Onboard revenue add-on per occupied passenger-km equivalent in the current simplified NATM implementation. | `revenue` | `operator_name` | `segment` | `unit` should describe the onboard spending basis |

### Technology cost and availability

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `technology_dynamic_price_index` | Dynamic multiplier added to the base technology capex for a given year. | `cost_index` | `technology_name` | `segment` | `unit` should be `share` |
| `technology_availability` | Commercial availability flag for a technology in that year. | `availability` | `technology_name` | `segment` | `unit` should indicate a flag |
| `infrastructure_availability` | Availability flag for the required port, bunkering, or infrastructure setup. | `availability` | `country`, `technology_name` | `segment` | `unit` should indicate a flag |
| `biofuel_availability` | Availability flag for a specific biofuel-enabled technology or pathway. | `availability` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |

### Branch and blend logic

| variable_name | Definition | Recommended variable_group | Required scope columns | Optional scope columns | Other required columns |
| --- | --- | --- | --- | --- | --- |
| `maximum_secondary_energy_share` | Maximum usable secondary-energy share for a technology in that scope. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should be `share` |
| `maximum_secondary_energy` | Legacy alias supported by the model for the same cap. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should be `share` |
| `secondary_energy_cap_active` | Flag controlling whether a technology can use its configured secondary energy stream. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
| `maximum_cap_secondary_energy` | Legacy alias supported by the model for the same cap-active branch. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
| `drop_in_mandate_active` | Flag controlling whether drop-in mandate logic is active for that technology or pathway scope. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |
| `drop_in_fuel_mandate` | Legacy alias supported by the model for the same drop-in branch. | `policy` or `branch` | `country`, `technology_name`, `secondary_energy_carrier` | `segment`, `saf_pathway` | `unit` should indicate a flag |

## Practical Guidance

- For variables that should apply everywhere, leave scope columns blank.
- For operator-specific commercial inputs, fill `operator_name` and leave other
  unrelated scope columns blank.
- `technology_name` is the technology identity. Use `segment` only when the
  scenario value differs by operating segment.
- For fuel-specific rows, use `primary_energy_carrier` or
  `secondary_energy_carrier` as appropriate.
- For biofuel rows, also fill `saf_pathway` when pathway-specific behavior
  matters.
- Use `passenger_km_demand` as the yearly maritime-passenger growth driver
  instead of any percentage-based market-growth variable.

## Current Baseline Maritime Passenger Case

The baseline maritime-passenger case in
`data/baseline-maritime-passenger-transition/maritime_scenario.csv` includes
examples for the maritime-passenger variable families above, including:

- demand allocation through `passenger_km_demand` and `operator_market_share`
- class-specific occupancy assumptions
- class-specific ticket-rate assumptions
- onboard spending
- optional planned deliveries through `planned_delivery_count`
- policy, price, availability, and branch controls for technology adoption
