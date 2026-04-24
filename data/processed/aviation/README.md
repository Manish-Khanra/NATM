# Aviation Processed Outputs

This directory is reserved for generated aviation preprocessing outputs.

The preprocessing pipeline writes files such as:

- `opensky_aircraft_db_processed.csv`
- `aviation_fleet_stock_cleaned.csv`
- `aviation_fleet_stock_enriched.csv`
- `aviation_stock_matching_report.csv`
- `opensky_flightlist_processed.parquet`
- `aviation_activity_profiles_by_type.csv`
- `aviation_activity_profiles_by_operator_type.csv`
- `aviation_activity_profiles_by_airport_type.csv`
- `aviation_activity_profiles_by_registration.csv`
- `aviation_activity_profiles.csv`
- `aviation_airport_allocation.csv`
- `aviation_regional_allocation.csv`
- `aviation_calibration_targets.csv`

These outputs remain separate from:

- case stock inputs
- technology catalogs
- yearly scenario files

so the observed baseline and the forward-looking simulation assumptions stay clearly separated.
