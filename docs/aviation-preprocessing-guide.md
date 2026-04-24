# Aviation Preprocessing Guide

This guide describes the new aviation data-ingestion and preprocessing workflow
that sits alongside the existing NATM aviation model.

The purpose of this workflow is to keep:

- observed stock and metadata
- empirical activity profiles
- calibration targets
- technology assumptions
- future scenario assumptions

clearly separated while still feeding empirically grounded aviation baselines
into the existing NATM architecture.

## 1. Architecture Role

The preprocessing layer does **not** replace the current aviation case format.
Instead, it prepares better aviation baseline inputs that can be merged into the
existing case structure.

The current NATM aviation simulation still centers on:

- `aviation_fleet_stock.csv`
- `aviation_technology_catalog.csv`
- `aviation_scenario.csv`

The preprocessing layer adds optional and intermediate files around that core:

- `opensky_aircraft_db_processed.csv`
- `aviation_fleet_stock_cleaned.csv`
- `aviation_fleet_stock_enriched.csv`
- `opensky_flightlist_processed.parquet`
- `aviation_activity_profiles_*.csv`
- `aviation_airport_allocation.csv`
- `aviation_regional_allocation.csv`
- `aviation_calibration_targets.csv`

The optional case-level bridge file is:

- `aviation_activity_profiles.csv`

If this file exists inside a case folder, the aviation case loaders merge it
onto the fleet stock baseline.

## 2. Package Layout

The preprocessing code lives in:

- `navaero_transition_model/aviation_preprocessing/`

Key modules:

- `stock_cleaner.py`
  Cleans and standardizes aviation fleet stock.
- `opensky_aircraft_db.py`
  Downloads and/or processes the OpenSky aircraft metadata database.
- `matching.py`
  Enriches stock with `registration`, `icao24`, `serial_number`,
  `is_german_flag`, `match_confidence`, and `match_method`.
- `flightlists.py`
  Ingests monthly OpenSky/Zenodo flight lists and stores a reusable processed
  table.
- `airport_metadata.py`
  Loads airport metadata and normalizes airport/region columns.
- `activity_profiles.py`
  Builds empirical activity profiles by type, operator/type, airport/type, and
  registration.
- `allocation.py`
  Builds German airport and regional allocation layers.
- `calibration.py`
  Builds Germany calibration targets and optional baseline scaling factors.
- `baseline.py`
  Merges stock plus activity into the final enriched aviation stock baseline.
- `pipeline.py`
  Orchestrates the preprocessing phases.
- `cli.py`
  Command-line entry point for the preprocessing workflow.

## 3. Processed Output Directory

Processed aviation files are written under:

```text
data/processed/aviation/
```

This keeps observed and derived baseline data separate from:

- case folders in `data/<case-name>/`
- simulation result folders in `simulation_results/`

## 4. Core Outputs

### 4.1 OpenSky aircraft database

Processed aircraft metadata output:

```text
data/processed/aviation/opensky_aircraft_db_processed.csv
```

Normalized core fields include:

- `icao24`
- `registration`
- `manufacturer_name`
- `model`
- `typecode`
- `operator`
- `owner`
- `country`
- `status`
- `built`
- `serial_number`

Derived helper fields:

- `registration_prefix`
- `built_year`
- `is_german_flag`

### 4.2 Matching-enriched fleet stock

Outputs:

- `aviation_fleet_stock_enriched.csv`
- `aviation_stock_matching_report.csv`

Matching enriches the stock with:

- `registration`
- `icao24`
- `serial_number`
- `is_german_flag`
- `match_confidence`
- `match_method`

Matching order:

1. exact multi-feature match
2. scored/fuzzy fallback
3. ambiguous handling when candidate separation is weak
4. unmatched if confidence is too low

Low-confidence matches are not silently accepted as exact.

### 4.3 Flightlist processing

Processed flightlist output:

```text
data/processed/aviation/opensky_flightlist_processed.parquet
```

The ingestor supports:

- multiple monthly CSV or CSV.GZ inputs
- year filtering
- airport filtering
- country filtering with airport metadata
- aircraft-type filtering

If a parquet engine is unavailable in a local environment, the code falls back
to a compatible serialized store under the same path so the workflow can still
run locally. In a normal configured environment, this file should be written as
true parquet.

### 4.4 Activity profiles

Outputs:

- `aviation_activity_profiles_by_type.csv`
- `aviation_activity_profiles_by_operator_type.csv`
- `aviation_activity_profiles_by_airport_type.csv`
- `aviation_activity_profiles_by_registration.csv`

These profiles include metrics such as:

- annual departures
- average route distance
- median route distance
- domestic share
- international share
- short/medium/long-haul shares
- annual distance by aircraft where possible

### 4.5 Airport and regional allocation

Outputs:

- `aviation_airport_allocation.csv`
- `aviation_regional_allocation.csv`

These are territorial activity layers for German airport departures and are
separate from legal German-flag fleet ownership.

### 4.6 Calibration targets

Output:

```text
data/processed/aviation/aviation_calibration_targets.csv
```

This file stores official totals and optional calibration factors for Germany.
It is intentionally separate from the yearly scenario CSV.

### 4.7 Final enriched aviation baseline

Outputs:

- `aviation_fleet_stock_enriched.csv`
- `aviation_activity_profiles.csv`

These are the bridge files for NATM integration.

They can carry fields such as:

- `registration`
- `icao24`
- `is_german_flag`
- `annual_flights_base`
- `annual_distance_km_base`
- `domestic_activity_share_base`
- `international_activity_share_base`
- `mean_stage_length_km_base`
- `fuel_burn_per_year_base`
- `baseline_energy_demand`
- `airport_allocation_group`
- `main_hub_base`
- `match_confidence`
- `match_method`
- `activity_assignment_method`

Assignment priority in the baseline builder is:

1. registration-level
2. operator × type
3. type-level
4. segment fallback

## 5. How `run.py` launches preprocessing

The preprocessing workflow can be launched in two ways:

- directly with `natm-aviation-preprocess`
- through the reference-style [run.py](C:/Manish_REPO/NATM/run.py:1) launcher

Inside `run.py`, preprocessing is triggered by:

```python
selected_mode = "aviation_preprocessing"
selected_example = "small_with_aviation_passenger"
```

The preprocessing recipe lives in the selected case's `scenario.yaml`, under:

```yaml
preprocessing:
  aviation:
    enabled: true
```

For the baseline passenger case, this points to:

- `data/baseline-transition/aviation_fleet_stock.csv`
- `data/examples/aviation_preprocessing/opensky_aircraft_db_sample.csv`
- `data/examples/aviation_preprocessing/opensky_flightlists/`
- `data/examples/aviation_preprocessing/airports_sample.csv`
- `data/baseline-transition/aviation_technology_catalog.csv`
- `data/examples/aviation_preprocessing/germany_calibration_input.csv`

So if you press Run in VS Code with those two lines set, `run.py` does not
start the diffusion simulation. Instead, it runs the aviation preprocessing
pipeline and writes outputs into:

- `data/processed/aviation/`

### Internal step diagram

```text
run.py
  -> selected_mode = "aviation_preprocessing"
  -> selected_example = "small_with_aviation_passenger"

scenario.yaml preprocessing.aviation loads:
  -> aviation_fleet_stock.csv
  -> opensky_aircraft_db_sample.csv
  -> opensky_flightlists/
  -> airports_sample.csv
  -> aviation_technology_catalog.csv
  -> germany_calibration_input.csv

Phase 1
  -> clean stock
  -> process OpenSky aircraft DB
  -> match stock to OpenSky
  -> write:
     - aviation_fleet_stock_cleaned.csv
     - opensky_aircraft_db_processed.csv
     - aviation_fleet_stock_enriched.csv
     - aviation_stock_matching_report.csv

Phase 2
  -> ingest monthly flightlists
  -> join airport metadata
  -> compute route distances
  -> build activity profiles
  -> write:
     - opensky_flightlist_processed.parquet
     - aviation_activity_profiles_by_type.csv
     - aviation_activity_profiles_by_operator_type.csv
     - aviation_activity_profiles_by_airport_type.csv
     - aviation_activity_profiles_by_registration.csv

Phase 3
  -> build airport allocation
  -> build regional allocation
  -> build calibration targets
  -> merge stock + activity into enriched baseline
  -> write:
     - aviation_airport_allocation.csv
     - aviation_regional_allocation.csv
     - aviation_calibration_targets.csv
     - aviation_fleet_stock_enriched.csv
     - aviation_activity_profiles.csv

Then later in NATM simulation
  -> case loader reads aviation_activity_profiles.csv if present
  -> merges it onto aviation_fleet_stock.csv
  -> Fleet uses empirical baseline activity and energy where available
  -> current decision logic stays unchanged
```

## 6. German-Flag vs Territorial Filters

Reusable utilities exist for both concepts:

- `filter_german_flag_fleet()`
- `filter_german_airport_departures()`

German-flag definition:

- `registration` begins with `D-`

This is intentionally different from:

- `operator_country == Germany`
- departures from German airports

## 7. NATM Integration

The aviation case-data layer now supports an optional file:

```text
data/<case-name>/aviation_activity_profiles.csv
```

If present:

1. it is loaded by the aviation case-data class
2. it is merged onto the fleet stock baseline
3. missing values are filled from type-level and then segment-level defaults

The `Fleet` object then uses the empirical fields where available and falls
back to the current generic behavior otherwise.

Important `Fleet` methods now include:

- `assign_baseline_activity_profiles()`
- `apply_activity_fallbacks()`
- `estimate_baseline_energy_demand()`
- `annual_flights_for()`
- `annual_distance_km_for()`
- `baseline_energy_demand_for()`

The current aviation decision logic is preserved:

- technology availability filtering
- infrastructure availability filtering
- SAF availability filtering
- ETS allowance accounting
- NPV / payback style evaluation
- planned deliveries before endogenous additions

The new empirical fields change baseline utilization and energy-demand inputs;
they do not replace the existing aviation investment logic.

## 8. Example Synthetic Inputs

Synthetic example inputs live under:

```text
data/examples/aviation_preprocessing/
```

They are intentionally small and useful for:

- local testing
- debugging the pipeline
- understanding expected file shapes

Included example files:

- `opensky_aircraft_db_sample.csv`
- `opensky_flightlists/flightlist_202201_sample.csv`
- `airports_sample.csv`
- `germany_calibration_input.csv`

## 9. CLI and `run.py` Usage

Install the project normally:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

Then run the preprocessing CLI:

```powershell
natm-aviation-preprocess `
  --stock-input data\baseline-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-transition\aviation_technology_catalog.csv `
  --calibration-input data\examples\aviation_preprocessing\germany_calibration_input.csv
```

This command can run Phase 1 through Phase 3 of the new preprocessing layer.

To add OpenAP-based baseline fuel and emissions estimation, install the optional
dependency group and pass `--estimate-openap-fuel`:

```powershell
python -m pip install -e .[openap]

natm-aviation-preprocess `
  --stock-input data\baseline-transition\aviation_fleet_stock.csv `
  --opensky-raw data\examples\aviation_preprocessing\opensky_aircraft_db_sample.csv `
  --flightlist-folder data\examples\aviation_preprocessing\opensky_flightlists `
  --airport-metadata data\examples\aviation_preprocessing\airports_sample.csv `
  --technology-catalog data\baseline-transition\aviation_technology_catalog.csv `
  --calibration-input data\examples\aviation_preprocessing\germany_calibration_input.csv `
  --estimate-openap-fuel `
  --openap-mode synthetic
```

You can also launch the same synthetic workflow through `run.py`:

```powershell
python run.py --mode aviation_preprocessing --example small_with_aviation_passenger
```

With OpenAP enabled through `run.py`:

```powershell
python run.py `
  --mode aviation_preprocessing `
  --example small_with_aviation_passenger `
  --estimate-openap-fuel `
  --openap-mode synthetic
```

Or by editing the reference-style config block near the bottom of
[run.py](C:/Manish_REPO/NATM/run.py:1) and then pressing Run in VS Code.

## 10. OpenAP-Based Fuel Demand And Emissions Estimation

OpenAP is used only in preprocessing. NATM does not call OpenAP inside every
Mesa agent step. The intended workflow is:

```text
OpenSky / Zenodo flight data
  -> aviation preprocessing
  -> OpenAP flight-level fuel and emissions estimates
  -> aggregated aviation_activity_profiles.csv
  -> NATM Mesa diffusion simulation
```

This keeps flight-performance estimation separate from future technology
diffusion. OpenAP estimates baseline operational fuel and emissions intensities;
NATM then evolves technology shares, energy carriers, costs, policies, and
emissions factors through the simulation years.

### Input Modes

The first robust implementation focuses on trip-level monthly flight lists. A
row may contain `flight_id` or `callsign`, `icao24`, `registration`, `typecode`
or `aircraft_type`, `origin`, `destination`, `firstseen`, `lastseen`, `day`, and
optionally `distance_km`. If `distance_km` is missing, route distance is
calculated from airport coordinates and then adjusted with the configured route
extension factor.

Trajectory-level estimation is exposed as a secondary function-level extension.
It groups points by `flight_id`, sorts by timestamp, estimates time-step fuel
flow, and integrates fuel and emissions. The current example workflow uses the
synthetic trip-level mode because Zenodo/OpenSky monthly flight lists are
normally flight-list data, not full trajectories.

### Initial Mass Estimation

For trip-level OpenAP estimation, NATM now estimates the initial aircraft mass
from the best available case data:

```text
initial_mass =
  operating_empty_weight
  + passenger_payload
  + cargo_payload
  + estimated_block_fuel
```

The preferred source for `operating_empty_weight`, `mtow`,
`fuel_capacity_kwh`, cabin seats, and cargo payload capacity is the aviation
technology catalog joined through `current_technology`. Passenger payload uses
the scenario occupancy variables (`economy_occupancy`, `business_occupancy`,
`first_occupancy`) and default passenger-plus-baggage masses. Cargo payload uses
`payload_capacity_kg * load_factor` for aviation cargo cases. Passenger belly
cargo is intentionally left at zero until a clear belly-cargo capacity field is
available.

The estimated block fuel is a first-pass proxy:

```text
block_fuel_kg =
  fuel_capacity_kg
  * min(flown_distance_km / aircraft_range_km, 1)
  * block_fuel_reserve_factor
```

The default `block_fuel_reserve_factor` is `1.15`. The resulting mass is clamped
between the minimum physical mass (`OEW + payload`) and MTOW. If the required
stock, technology, or scenario fields are missing, preprocessing falls back to
the older MTOW-fraction estimate and records the method in
`mass_estimation_method`.

### Aircraft Type Mapping

Aircraft type codes are mapped in
`navaero_transition_model/aviation_preprocessing/aircraft_type_mapping.py`.
The mapping result records:

- `raw_type`
- `openap_type`
- `mapping_status`: `exact`, `fallback`, `unsupported`, or `missing`
- `mapping_note`

Important fallbacks are logged rather than hidden. For example, `A20N` first
tries `A20N`; if unsupported by the installed OpenAP version it falls back to
`A320`. `B38M` can fall back to `B738`, and `E195` can fall back to `E190`.
The mapping log is written to:

```text
data/processed/aviation/openap_aircraft_type_mapping_log.csv
```

### Outputs

When `--estimate-openap-fuel` is enabled, the preprocessing layer writes:

- `openap_flight_fuel_emissions.csv`
- `openap_aircraft_type_summary.csv`
- `openap_route_summary.csv`
- `openap_aircraft_type_mapping_log.csv`
- `openap_validation_report.txt`

It also enriches or creates:

```text
data/processed/aviation/aviation_activity_profiles.csv
```

The OpenAP profile columns include `openap_type`, `number_of_trips`,
`total_distance_km`, `total_fuel_kg`, `total_energy_mwh`, `total_co2_kg`,
`total_nox_kg`, `fuel_kg_per_km`, `energy_mwh_per_km`, `co2_kg_per_km`,
`average_flight_distance_km`, and `average_fuel_kg_per_flight`. Existing NATM
activity columns such as `annual_flights_base`, `annual_distance_km_base`,
`mean_stage_length_km_base`, `baseline_energy_demand`, and
`fuel_burn_per_year_base` are preserved.

The flight-level file also records mass-estimation diagnostics:
`oew_kg`, `passenger_payload_kg`, `cargo_payload_kg`,
`estimated_block_fuel_kg`, and `mass_estimation_method`.

### Technology Catalog Connection

The core model still uses `technology_name` as the unique technology lookup key.
Technology catalogs may optionally include:

- `openap_type`
- `reference_fuel_kg_per_km`
- `reference_energy_mwh_per_km`
- `reference_co2_kg_per_km`
- `fuel_estimation_source`
- `fuel_estimation_mode`

These fields are optional reference metadata. They do not replace the existing
technology-catalog cost, performance, fuel-carrier, SAF, ETS, and feasibility
fields.

### Limitations

- OpenAP estimates operational fuel demand, not airline-reported fuel uplift.
- Trip-level mode approximates climb, cruise, and descent using a synthetic
  mission profile.
- If only groundspeed is available in trajectory mode, it can be used as a TAS
  proxy.
- Initial aircraft mass uses OEW, passenger/cargo payload, and estimated block
  fuel when those inputs are available; otherwise it falls back to an MTOW
  fraction.
- A320neo/A20N is used directly only if the installed OpenAP version supports it;
  otherwise fallback mapping is recorded.
- Non-CO2 emissions depend on OpenAP aircraft and engine support.
- Taxi/LTO fuel is not included in the first version.
- OpenAP estimates baseline fuel/emission intensities; future transition effects
  remain handled by NATM diffusion and technology-catalog logic.

## 11. Technology Efficiency Semantics

The preprocessing layer uses the technology catalog only for performance and
energy-efficiency assumptions. The lookup is based on unique `technology_name`.
For real aviation data this can be a specific model such as `A320neo`,
`A321XLR`, or `B787-9`, each with its own `kilometer_per_kwh`.

`segment` is still used for demand, market-share, activity fallback, planned
deliveries, and reporting. It is not part of the technology identity. The
example technology catalogs may still carry a `segment` column as optional
operating-context metadata, but lookup is name-based.

## 12. Recommended Workflow

1. Clean and enrich the stock with OpenSky aircraft metadata.
2. Ingest and process the historical flight lists.
3. Build activity profiles.
4. Build airport/regional allocation tables.
5. Build calibration targets.
6. Build the enriched baseline stock plus `aviation_activity_profiles.csv`.
7. Copy the relevant baseline files into the aviation case folder when ready.
8. Run the existing NATM aviation model without changing the technology catalog
   or yearly scenario design.
