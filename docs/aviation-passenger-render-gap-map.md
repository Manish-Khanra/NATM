# Aviation Passenger Render Gap Map

This note tracks how the current Mesa `legacy_weighted_utility` implementation
in NATM compares to the old `render-Aviation` aviation-passenger model,
especially `aviation/passenger/source/airline_agent_1.py`.

The intent is to separate:

- `ported`: behavior already represented in NATM
- `simplified`: behavior represented, but with a cleaner or lighter mechanism
- `corrected`: behavior intentionally changed because the old implementation was
  clearly brittle or logically broken
- `pending`: not yet carried over

## Core Yearly Flow

- `ported`: yearly update of existing fleet energy/emissions
- `ported`: yearly technology replacement for due aircraft
- `ported`: yearly fleet growth additions
- `ported`: yearly technology investment tracking
- `ported`: yearly technology diffusion, energy, emissions, and cost outputs

## Decision Logic

- `ported`: segment-specific candidate technology choice
- `ported`: technology and infrastructure availability filtering
- `ported`: economic utility based on payback/NPV over technology lifetime
- `ported`: environmental utility using threshold-style partial utilities for
  HC, CO, NOx, smoke, and CO2 factors
- `ported`: weighted total utility using operator economic and environmental
  preferences
- `ported`: technology dynamic price index in capex
- `ported`: maintenance, wages, landing fees, depreciation, salvage value, and
  interest rate in payback evaluation

## Fuel and Emissions

- `ported`: drop-in SAF behavior through mandate-constrained secondary share
- `ported`: non-drop-in alternative behavior through maximum secondary share
- `ported`: primary and secondary energy quantity tracking
- `ported`: energy-carrier-specific fuel demand outputs
- `ported`: yearly carbon-emission outputs by airline, technology, and carrier
- `ported`: ETS handling now uses sequential per-aircraft remaining-allocation
  tracking across each airline's yearly fleet update and replacement order
- `ported`: SAF candidate filtering can now honor pathway-specific scenario
  availability flags in the cleaner NATM case structure
- `ported`: old SAF/non-SAF branch behavior can now be expressed in the single
  scenario table through `secondary_energy_cap_active`,
  `drop_in_mandate_active`, and `maximum_secondary_energy_share`

## Growth and Fleet Management

- `ported`: aircraft additions under market growth
- `ported`: unique aircraft IDs for added aircraft
- `simplified`: NATM grows by each segment actually present in the airline
  fleet, instead of the old hard-coded selected segment behavior
- `corrected`: NATM does not reproduce the old hard-coded `selected_segment = 10`
  growth rule because it would be a bug in the new model
- `corrected`: NATM does not reproduce the old broken `if id_technology == 1 or
  2 or 3 ...` logic because that condition is invalid Python behavior

## Data Structure

- `ported`: fleet-stock-based initial aircraft representation
- `ported`: technology catalog as explicit technology rows
- `ported`: scenario table as yearly scope-based values
- `corrected`: NATM removes Melodie-style ID tables, relation tables, and
  `RenderKey` indirection
- `corrected`: NATM uses explicit columns and domain objects instead of database
  reconstruction logic

## Outputs

- `ported`: technology adoption by year per airline
- `ported`: investment cost by year per airline
- `ported`: fuel demand and carbon emissions by year, airline, segment,
  technology, and energy carrier
- `simplified`: NATM writes CSV outputs directly rather than using the old
  database-plus-Excel export flow

## Remaining Gaps

- `pending`: direct parity test against a controlled old-model reference case
- `pending`: calibration against real aviation-passenger input datasets
- `pending`: any old scenario branches that depended on Melodie-only tables not
  yet mapped into the 3-file NATM case structure

## Immediate Fidelity Improvements Applied In This Refactor

- added conventional long-haul technology options to avoid unrealistic hydrogen
  defaults in the baseline case
- added hydrogen and battery price rows to avoid zero-cost alternative energy
  artifacts
- added fuller revenue-side scenario rows for business, first-class, and
  freight assumptions
- added operator preference and ETS fields to the sample fleet-stock input
- added scenario-side SAF branch controls so drop-in and capped-secondary-share
  behavior can be represented without extra relation tables
