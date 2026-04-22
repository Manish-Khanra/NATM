# Maritime Cargo Render Gap Map

This document tracks the current fidelity status between the old
`render-Aviation` maritime cargo model and the current NATM maritime cargo
implementation.

Primary old-model references:

- `render-Aviation/maritime/cargo/source/model.py`
- `render-Aviation/maritime/cargo/source/shipline_agent_1.py`

Primary NATM references:

- [model.py](C:/Manish_REPO/NATM/navaero_transition_model/core/model.py:1)
- [maritime_cargo_shipline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/maritime_cargo_shipline.py:1)
- [legacy_weighted_utility_maritime_cargo.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility_maritime_cargo.py:1)
- [maritime_cargo_case.py](C:/Manish_REPO/NATM/navaero_transition_model/core/case_inputs/maritime_cargo_case.py:1)

## Scope

This gap map is about behavioral fidelity, not package architecture.

So the questions here are:

- which old maritime cargo equations and rules are already represented in NATM
- which ones are only approximated or simplified
- which ones were intentionally changed
- which ones are still missing

## Overall Status

Current status:

- yearly shipline-level replacement and adoption logic: `ported`
- weighted utility decision structure: `ported`
- maritime-specific environmental utility thresholds: `ported`
- reported-emission handling: `ported`
- capacity-driven growth using `tkm/year`: `intentionally redesigned`
- old Melodie ID-table data plumbing: `intentionally replaced`
- full equation-by-equation parity with every old branch: `not complete yet`

## High-Level Comparison

| Topic | Old render-Aviation maritime cargo | NATM maritime cargo | Status |
|---|---|---|---|
| Simulation loop | yearly update fuel -> update vessels -> save outputs | yearly agent step -> update environment -> collect outputs | ported |
| Agent granularity | one shipline agent with vessel fleet | one Mesa shipline agent with vessel fleet | ported |
| Fleet replacement | replace vessel when replacement year is reached | replace vessel when replacement year is reached | ported |
| Technology choice | weighted utility over feasible technologies | weighted utility over feasible technologies | ported |
| Economic utility | payback/NPV style | payback/NPV style | ported |
| Environmental utility | CO2 + SOx + NOx + SN thresholds | CO2 + SOx + NOx + SN thresholds | ported |
| Technology availability | scenario-gated | scenario-gated | ported |
| Infrastructure availability | scenario-gated | scenario-gated | ported |
| Biofuel / secondary-energy logic | mandate and cap branches | mandate and cap branches | ported |
| Market growth | percent-growth heuristic | `freight_tonne_km_demand` + `operator_market_share` | intentionally redesigned |
| Planned deliveries | not a clean standalone mechanism | explicit `planned_delivery_count` rows | intentionally redesigned |
| Data management | many IDs / relation tables | case CSVs with direct scopes | intentionally redesigned |

## Detailed Status

### 1. Yearly Simulation Sequence

Old model:

- update year key
- update current-fleet fuel/emission state
- update due vessels
- optionally add vessels
- save yearly technology result

NATM:

- update current-year metrics for non-replacement vessels
- replace due vessels
- add planned or endogenous growth vessels if a residual `tkm` gap remains
- collect model and agent outputs through Mesa plus detailed exporters

Status: `ported`

Comment:

- the mechanics are the same in intent, but NATM routes them through Mesa agent
  stepping rather than a Melodie environment orchestrator

### 2. Fleet Initialization

Old model:

- shipline fleet built from vessel relations
- initial vessel type, segment, technology, energy carriers, and replacement year

NATM:

- fleet built directly from [maritime_fleet_stock.csv](C:/Manish_REPO/NATM/data/baseline-maritime-cargo-transition/maritime_fleet_stock.csv:1)
- replacement year derived from age + technology lifetime in
  [fleet.py](C:/Manish_REPO/NATM/navaero_transition_model/core/fleet_management/fleet.py:1)

Status: `ported`

Difference:

- NATM uses direct CSV columns rather than old relation tables and RenderKeys

### 3. Technology Candidate Filtering

Old model:

- valid technologies depend on vessel type + segment
- then filtered by `technology_availability`
- then filtered by `infrastructure_availability`
- then further constrained by energy-carrier branches

NATM:

- candidates loaded from the segment rows in the technology catalog
- filtered by:
  - `technology_availability`
  - `infrastructure_availability`
  - `biofuel_availability`
  - `service_entry_year`

Status: `ported`

Open gap:

- old model encoded candidate feasibility partly through explicit relation tables
- NATM currently assumes the catalog rows already reflect that vessel/segment compatibility

### 4. Revenue Calculation

Old model:

- revenue is load factor × freight rate × cargo basis × daily activities
- cargo basis branch:
  - if `net_tonnage` is missing: use `max_tanker_size`
  - else: use `gross_tonnage * net_tonnage / 100`

NATM:

- revenue is load factor × freight rate × cargo basis × trip length × trip days
- cargo basis branch in [maritime_cargo_shipline.py](C:/Manish_REPO/NATM/navaero_transition_model/core/agent_types/maritime_cargo_shipline.py:1):
  - prefer `gross_tonnage * net_tonnage_share`
  - else `max_tanker_size_tonnes`
  - else `payload_capacity_kg`

Status: `ported`

Important note:

- NATM uses `net_tonnage_share` as a fractional share, while the old model used
  `net_tonnage / 100`
- behavior is equivalent if the data is translated consistently

### 5. Operating Cost Composition

Old model:

- operation cost includes:
  - energy cost
  - carbon cost on reported emissions
- payback cashflow also includes:
  - maintenance
  - wages
  - port fees
  - cargo handling charges
  - depreciation

NATM:

- operation metrics include:
  - energy cost
  - carbon cost on chargeable reported emissions
- payback cashflow includes:
  - maintenance
  - crew cost
  - port fees
  - cargo handling
  - depreciation

Status: `partially ported`

What matches:

- same major categories exist

What still differs:

- the exact coefficients differ from the old model in some places
- NATM currently uses:
  - crew cost `0.18 * revenue`
  - port fees `0.08 * revenue`
  - cargo handling `0.06 * revenue`
- old model used:
  - wages `0.24 * revenue`
  - port fees `0.10 * revenue`
  - cargo handling `0.10 * revenue`

This is still an active fidelity gap.

### 6. Carbon and Reported Emissions

Old model:

- total CO2 often computed from `carbondioxide_factor * total_fuel`
- reported emissions then computed as:
  - `reported_emission = emission_total * reported_emission`

NATM:

- now follows the same pattern:
  - prefer `carbondioxide_factor * total_energy`
  - then apply `reported_emission` share from scenario or catalog
- carbon price uses `carbon_tax` first, then `carbon_price`

Status: `ported`

Comment:

- this was one of the main fidelity fixes in the latest pass

### 7. ETS / Chargeable Emissions

Old model:

- carbon cost applied to reported emissions
- free allocation logic was present but less cleanly integrated across the whole flow

NATM:

- yearly free ETS balance carried through:
  - current fleet update
  - replacements
  - growth additions
- `chargeable_emission` and `remaining_ets_allocation` are exposed in outputs

Status: `ported and improved`

Comment:

- NATM preserves the old modeling idea but makes it more explicit and traceable

### 8. Secondary Energy and Biofuel Branches

Old model:

- separate branches for:
  - drop-in mandate active
  - capped secondary-energy share
  - no secondary-energy share
- biofuel path could use tertiary energy price

NATM:

- explicit branch logic in
  [legacy_weighted_utility_maritime_cargo.py](C:/Manish_REPO/NATM/navaero_transition_model/core/decision_logic/legacy_weighted_utility_maritime_cargo.py:1)
- supports:
  - `biofuel_mandate`
  - `maximum_secondary_energy_share`
  - `maximum_secondary_energy`
  - `maximum_cap_secondary_energy`
  - `drop_in_fuel_mandate`
  - `tertiary_energy_price`

Status: `ported`

### 9. Environmental Utility

Old model:

- utility uses four pollutant partial utilities:
  - CO2
  - SOx
  - NOx
  - smoke number
- each pollutant has its own thresholds and score ladder

NATM:

- now uses maritime-specific partial utility functions for:
  - CO2
  - SOx
  - NOx
  - smoke number
- weights follow the old maritime structure:
  - CO2 `0.30`
  - SOx `0.30`
  - NOx `0.20`
  - SN `0.20`

Status: `ported`

Comment:

- this was another key fidelity improvement in the latest pass

### 10. Weighted Utility Combination

Old model:

- `economic_utility * economic_weight + environmental_utility * environmental_weight`

NATM:

- same base weighted structure
- plus a small policy bonus for non-conventional technologies

Status: `partially ported`

Difference:

- the policy bonus is a NATM extension, not a direct old-model copy

### 11. Growth / Fleet Expansion

Old model:

- growth driven by `market_growth`
- convert growth difference into number of vessels

NATM:

- growth driven by:
  - `freight_tonne_km_demand`
  - `operator_market_share`
  - actual post-replacement fleet capacity
  - `planned_delivery_count`

Status: `intentionally redesigned`

Why changed:

- the old percent-growth rule is weaker from a business-planning perspective
- NATM now uses demand-driven capacity planning, consistent with the aviation
  cargo refactor

### 12. Data Structures

Old model:

- many Melodie relation tables, IDs, and RenderKey lookups

NATM:

- case-local CSVs:
  - [maritime_fleet_stock.csv](C:/Manish_REPO/NATM/data/baseline-maritime-cargo-transition/maritime_fleet_stock.csv:1)
  - [maritime_technology_catalog.csv](C:/Manish_REPO/NATM/data/baseline-maritime-cargo-transition/maritime_technology_catalog.csv:1)
  - [maritime_scenario.csv](C:/Manish_REPO/NATM/data/baseline-maritime-cargo-transition/maritime_scenario.csv:1)

Status: `intentionally redesigned`

Comment:

- this is a major architectural improvement, not a fidelity bug

## Intentional Corrections

These are places where NATM intentionally does **not** copy the old model
literally.

### 1. Old boolean-condition bugs

The old code contains patterns like:

- `if x == 1 or 2 or 3`

That is not valid membership logic in Python and becomes effectively always
truthy.

NATM status: `corrected intentionally`

### 2. Carbon-cost sign

The old model appears to subtract carbon cost inside `operation_costs` in some
branches.

NATM status: `corrected intentionally`

Reason:

- carbon cost is treated as a real added cost in NATM

### 3. NPV capex treatment

The old payback loop mixes initial capex and yearly cashflow accumulation in a
way that can be hard to interpret and may over-apply the vessel price.

NATM status: `corrected intentionally`

Reason:

- NATM keeps capex as an upfront investment in the NPV/payback calculation

## Remaining Gaps

These are the main remaining maritime cargo fidelity gaps.

### 1. Operating-cost coefficients

Still to align more closely with the old maritime cargo model:

- wages / crew share
- port-fee share
- cargo-handling share

### 2. Exact utility normalization

The current NATM payback-to-utility mapping is close in structure, but should
still be checked more strictly against the old implementation for exact range
behavior.

### 3. Vessel-type compatibility constraints

The old model encoded some feasibility through explicit relation tables.
NATM currently assumes that:

- the maritime technology catalog rows are already valid for the segment

If needed, a future tighter port could add explicit vessel-type compatibility
columns.

### 4. Output parity audit

NATM now exports the key result families, but we have not yet completed a
strict old-vs-new output comparison for:

- yearly technology adoption
- energy demand by carrier
- reported vs chargeable emissions
- investment costs

## Current Practical Conclusion

Maritime cargo in NATM is now at this state:

- architecture: `done`
- demand-driven growth design: `done`
- core adoption decision logic: `done`
- maritime-specific pollutant utility logic: `done`
- reported-emission and carbon-tax handling: `done`
- strict final parity with every old coefficient/branch: `not complete yet`

So the remaining work is concentrated and understandable. It is no longer
“build the maritime cargo model,” but rather “tighten the last fidelity gaps.”

## Recommended Next Steps

1. Align the remaining operating-cost coefficients with the old maritime cargo model.
2. Add a maritime cargo scenario reference document, similar to the aviation ones, if broader input documentation is needed.
3. Run a controlled old-vs-new comparison once matching reference outputs are available.
