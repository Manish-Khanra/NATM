# Aviation Passenger Mesa Port

This note defines how NATM should port the aviation-passenger diffusion logic
from the old `render-Aviation` Melodie model into a cleaner Mesa-native design.

## Objective

Port the real diffusion and decision logic from:

- `aviation/passenger/source/model.py`
- `aviation/passenger/source/airline_agent_1.py`
- `aviation/passenger/source/scenario.py`
- `aviation/passenger/source/data_loader.py`
- `aviation/passenger/source/data_collector.py`

while removing the old dependency on many separate ID tables, relation tables,
and `RenderKey`-based lookups.

`airline_agent_1.py` is the primary behavioral baseline. `airline_agent.py` is
only a secondary reference for cross-checking.

## Legacy Flow

The old model runs the following yearly sequence:

1. Set the current simulation year.
2. Update fuel and emissions for the existing fleet.
3. Replace aircraft that reach their replacement year.
4. Optionally expand the fleet based on market growth.
5. Save fleet technology results for diffusion, energy, emissions, and costs.

The key behavioral logic lives in `airline_agent_1.py`.

### Replacement Decision

For each aircraft due for replacement:

1. Identify the aircraft segment.
2. Enumerate candidate technologies valid for that segment.
3. Filter by technology availability and infrastructure availability.
4. For each feasible option, compute:
   - economic utility
   - environmental utility
   - total weighted utility
5. Choose the technology with the strongest total utility.
6. Update aircraft technology, fuel carriers, emissions, energy use, ETS, and
   future replacement year.

### Economic Utility

Economic utility is based on payback timing over technology lifetime.

The old agent computes:

- annual revenue
- operational energy cost
- maintenance cost
- wages
- landing fees
- depreciation
- salvage value
- NPV/payback year using an interest rate

The utility score is:

`economic_utility = ((lifetime + 1) - payback_year) / lifetime`

### Environmental Utility

Environmental utility is a weighted sum of partial utilities for:

- hydrocarbon
- carbon monoxide
- nitrogen oxide
- smoke number
- primary-energy CO2
- secondary-energy CO2

The old model bins each pollutant into stepwise partial scores rather than using
continuous normalization.

### Total Utility

The old airline decision combines:

`total_utility = economic_utility * eco_weight + environmental_utility * env_weight`

where the weights are airline-specific.

### Growth Logic Added In `airline_agent_1.py`

`airline_agent_1.py` added:

- `add_aircraft()`
- `get_target_segment()`
- `get_new_aircraft_id()`

This means the aviation-passenger port should support both:

- replacement-driven diffusion
- market-growth-driven fleet expansion

## Legacy Problems We Should Not Copy

The old model contains behavior we should preserve conceptually but not copy
literally:

- broken Python conditions such as `if id_technology == 1 or 2 or 3`
- duplicated agent files with diverging logic
- a hard-coded segment choice in growth logic
- a pseudo-random chooser that often behaves deterministically
- many separate files that only exist to rebuild simple relations
- `RenderKey` lookup indirection for data that should be direct columns

## Mesa Target Design

### Model

`NATMModel` should remain the Mesa `Model`, but aviation passenger should be
refactored into a more explicit substructure:

- case data loader
- technology catalog
- yearly scenario slicer
- airline agents
- optional world/environment state
- Mesa `DataCollector`

### Agents

Mesa airline agents should become true operator decision makers, not just sector
share containers.

Each airline agent should own:

- operator metadata
- decision weights
- free ETS allocation state
- fleet dataframe
- yearly technology investment results

Each fleet row should represent one aircraft.

### Environment

For aviation-passenger porting, the environment should not be the main storage
for all exogenous inputs. It should coordinate shared world state such as:

- infrastructure rollout
- fuel availability
- optional airport/country network effects

The old `environment.py` mostly acts as an orchestrator, so NATM should move
most exogenous scenario values into a dedicated scenario table instead.

## User-Facing Case Files

For aviation-passenger, the recommended case format is 3 CSV files.

### 1. `aviation_fleet_stock.csv`

One row per aircraft in the initial fleet.

Required columns:

- `aircraft_id`
- `operator_name`
- `operator_country`
- `aircraft_type`
- `segment`
- `haul`
- `status`
- `build_date`
- `startup_year`
- `aircraft_age_years`
- `current_technology`
- `primary_energy_carrier`
- `secondary_energy_carrier`
- `saf_pathway`

Recommended aircraft attributes:

- `seat_total`
- `range_km`
- `engine_count`
- `engine_manufacturer`
- `engine_type`
- `build_country`
- `delivery_date_operator`
- `exit_date_operator`

Recommended operator-level columns repeated on each row:

- `operator_economic_weight`
- `operator_environmental_weight`
- `free_ets_allocation`

This removes the need for:

- `ID_Airline.xlsx`
- `ID_Country.xlsx`
- `ID_Aircraft.xlsx`
- `Relation_Airline_Aircraft.xlsx`
- `Model_CountryAirlineCoverage.xlsx`
- `Parameter_Aircraft_StartupYear.xlsx`
- `Parameter_Aircraft_Age.xlsx`

### 2. `aviation_technology_catalog.csv`

One row per feasible segment-technology configuration.

Required columns:

- `technology_name`
- `segment`
- `primary_energy_carrier`
- `secondary_energy_carrier`
- `saf_pathway`
- `drop_in_fuel`
- `maximum_secondary_energy_share`
- `lifetime_years`
- `payback_interest_rate`
- `capex_eur`
- `maintenance_cost_share`
- `depreciation_cost_share`
- `kilometer_per_kwh`
- `trip_days_per_year`
- `fuel_capacity_kwh`
- `trip_length_km`
- `economy_seats`
- `business_seats`
- `first_class_seats`
- `mtow`
- `oew`
- `primary_energy_emission_factor`
- `secondary_energy_emission_factor`
- `hydrocarbon_factor`
- `carbon_monoxide_factor`
- `nitrogen_oxide_factor`
- `smoke_number_factor`

Optional columns:

- `technology_family`
- `service_entry_year`
- `minimum_airport_class`
- `technology_notes`

This removes the need for:

- most technology ID tables
- technology-fuel relation tables
- SAF relation tables
- segment-technology relation tables
- most static technology parameter tables

### 3. `aviation_scenario.csv`

One row per scenario variable and scope, with one column per simulation year.

This keeps the user-facing structure close to what you described and close to
the old model's wide year tables, while still letting NATM normalize it
internally after loading.

Required identifier columns:

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

Year columns:

- `2025`
- `2026`
- `2027`
- ...

Typical `variable_group` values:

- `price`
- `policy`
- `availability`
- `demand`
- `market`
- `cost_index`

Typical `variable_name` values:

- `primary_energy_price`
- `secondary_energy_price`
- `saf_energy_price`
- `carbon_price`
- `ets_allocation_factor`
- `saf_mandate`
- `technology_availability`
- `infrastructure_availability`
- `saf_availability`
- `secondary_energy_cap_active`
- `drop_in_mandate_active`
- `maximum_secondary_energy_share`
- `economy_occupancy`
- `business_occupancy`
- `first_occupancy`
- `economy_income`
- `business_income`
- `first_income`
- `freight_rate`
- `market_growth`
- `technology_dynamic_price_index`

This removes the need for nearly all old scenario Excel files.

## Internal Loading Strategy

The user-facing files can stay simple, but the loader should build clean
internal tables:

- `fleet_df`
- `technology_df`
- `scenario_long_df`

The scenario loader should internally melt year columns into:

- `year`
- `value`

so the simulation code can use direct filtering instead of `RenderKey`.

## Direct Replacement For `RenderKey`

The old model uses `RenderKey(id_country, id_airline, id_aircraft, id_segment,
id_technology, ..., year)` to fetch almost everything.

In NATM, replace that with explicit dataframe filters and typed objects:

- fleet row fields for aircraft state
- operator fields for airline state
- technology catalog filters for feasible options
- scenario filters for year-specific prices and policies

This keeps the model transparent and much easier to debug.

## Ported Mesa Decision Sequence

Each aviation airline agent should run this sequence every year:

1. Load the year's scenario slice for its operator/country/segment.
2. Update each existing aircraft's fuel use and emissions.
3. For each aircraft whose `replacement_year == current_year`:
   - derive feasible technology options from the catalog
   - apply availability and infrastructure filters
   - compute operating cost paths
   - compute payback year
   - compute environmental partial utilities
   - compute total utility
   - select the winning option
   - update aircraft state and investment cost
4. Apply optional growth logic from `airline_agent_1.py`.
5. Report fleet technology counts, energy use, emissions, and investment cost.

## Old-To-New Mapping

### File groups that become `aviation_fleet_stock.csv`

- `Model_CountryAirlineCoverage.xlsx`
- `Relation_Airline_Aircraft.xlsx`
- `Parameter_Aircraft_StartupYear.xlsx`
- `Parameter_Aircraft_Age.xlsx`
- airline and country name tables

### File groups that become `aviation_technology_catalog.csv`

- technology ID tables
- segment-technology relations
- technology-fuel relations
- SAF relations
- technology cost tables
- lifetime/efficiency/fuel-capacity tables
- emission-factor tables
- exhaust-emission tables

### File groups that become `aviation_scenario.csv`

- fuel price tables
- SAF price tables
- carbon tax / carbon price tables
- ETS allocation factor
- SAF mandate
- technology availability
- infrastructure availability
- SAF availability
- secondary-energy cap activation
- drop-in mandate activation
- yearly secondary-energy share overrides
- occupancy tables
- fare/income tables
- freight rate
- market growth
- dynamic price index

## Recommended First Implementation Slices

### Slice 1

Create a dedicated aviation-passenger loader that reads:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

and converts them into explicit dataframes.

### Slice 2

Replace the current simplified aviation operator logic with:

- per-airline fleet state
- aircraft replacement years
- technology option enumeration
- utility-based replacement decisions

### Slice 3

Implement the economic utility path:

- revenues
- operational cost
- maintenance
- wages
- landing fees
- depreciation
- salvage value
- NPV payback year

### Slice 4

Implement the environmental utility path using the old partial utility rules.

### Slice 5

Add fleet growth from `airline_agent_1.py`, but replace the old hard-coded
segment handling with a scenario-driven rule.

## Immediate Code Targets In NATM

The first new modules should likely be:

- `src/natm/core/aviation_passenger_loader.py`
- `src/natm/core/aviation_passenger_catalog.py`
- `src/natm/core/aviation_passenger_decision.py`

The current generic operator agent can then be refactored or subclassed into a
true aviation passenger airline agent.

## Decision Rules For The Port

- Preserve the old model's behavioral intent.
- Preserve the extra growth features from `airline_agent_1.py`.
- Do not preserve the old ID-table architecture.
- Do not preserve broken Python conditions.
- Keep case inputs human-manageable inside `data/<case-name>/`.
- Prefer direct named columns over synthetic IDs wherever possible.
