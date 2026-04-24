from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.aircraft_type_mapping import (
    AircraftTypeMappingResult,
    map_to_openap_type,
)
from navaero_transition_model.aviation_preprocessing.airport_metadata import load_airport_metadata
from navaero_transition_model.aviation_preprocessing.common import (
    ensure_parent_dir,
    great_circle_distance_km,
    read_parquet_compatible,
)
from navaero_transition_model.aviation_preprocessing.mission_profile import (
    generate_synthetic_mission_profile,
)
from navaero_transition_model.aviation_preprocessing.openap_backend import (
    OpenAPFuelConfig,
    OpenAPFuelEmissionBackend,
)
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner

RESULT_COLUMNS = (
    "flight_id",
    "aircraft_id",
    "registration",
    "operator_name",
    "raw_aircraft_type",
    "openap_type",
    "mapping_status",
    "mapping_note",
    "origin",
    "destination",
    "route",
    "date",
    "year",
    "distance_km",
    "flown_distance_km",
    "duration_min",
    "initial_mass_kg",
    "final_mass_kg",
    "oew_kg",
    "passenger_payload_kg",
    "cargo_payload_kg",
    "estimated_block_fuel_kg",
    "mass_estimation_method",
    "fuel_kg",
    "energy_mwh",
    "co2_kg",
    "h2o_kg",
    "nox_kg",
    "co_kg",
    "hc_kg",
    "soot_kg",
    "sox_kg",
    "estimation_mode",
    "quality_flags",
)


@dataclass(frozen=True)
class OpenAPFuelOutputs:
    flight_results: pd.DataFrame
    aircraft_type_summary: pd.DataFrame
    route_summary: pd.DataFrame
    activity_profiles: pd.DataFrame
    mapping_log: pd.DataFrame
    validation_report: str


def _first_value(row: pd.Series, names: tuple[str, ...], default: object = "") -> object:
    for name in names:
        if name not in row.index:
            continue
        value = row.get(name)
        if pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _date_and_year(row: pd.Series) -> tuple[str, int | None]:
    raw_date = _first_value(row, ("day", "date", "firstseen", "timestamp"), default="")
    date_value = pd.to_datetime(pd.Series([raw_date]), errors="coerce").iloc[0]
    if pd.isna(date_value):
        raw_year = pd.to_numeric(pd.Series([row.get("year", pd.NA)]), errors="coerce").iloc[0]
        return "", int(raw_year) if pd.notna(raw_year) else None
    return str(date_value.date()), int(date_value.year)


def _distance_from_row(row: pd.Series) -> tuple[float | None, set[str]]:
    flags: set[str] = set()
    for column in ("distance_km", "route_distance_km", "flown_distance_km"):
        value = pd.to_numeric(pd.Series([row.get(column, pd.NA)]), errors="coerce").iloc[0]
        if pd.notna(value) and float(value) > 0.0:
            return float(value), flags

    coordinate_columns = (
        "origin_latitude_deg",
        "origin_longitude_deg",
        "destination_latitude_deg",
        "destination_longitude_deg",
    )
    if all(column in row.index for column in coordinate_columns):
        values = pd.to_numeric(pd.Series([row[column] for column in coordinate_columns]))
        if values.notna().all():
            flags.add("synthetic_distance_used")
            return great_circle_distance_km(*[float(value) for value in values]), flags

    flags.add("missing_distance")
    return None, flags


def _empty_result(
    *,
    flight_row: pd.Series,
    mapping: AircraftTypeMappingResult,
    quality_flags: set[str],
) -> dict[str, object]:
    date, year = _date_and_year(flight_row)
    origin = str(_first_value(flight_row, ("origin", "origin_airport"), default="")).upper()
    destination = str(
        _first_value(flight_row, ("destination", "destination_airport"), default="")
    ).upper()
    return {
        "flight_id": _first_value(flight_row, ("flight_id", "callsign"), default=""),
        "aircraft_id": _first_value(flight_row, ("icao24", "aircraft_id"), default=""),
        "registration": _first_value(flight_row, ("registration",), default=""),
        "operator_name": _first_value(flight_row, ("operator_name", "operator"), default=""),
        "raw_aircraft_type": mapping.raw_type,
        "openap_type": mapping.openap_type or "",
        "mapping_status": mapping.mapping_status,
        "mapping_note": mapping.mapping_note,
        "origin": origin,
        "destination": destination,
        "route": f"{origin}-{destination}" if origin and destination else "",
        "date": date,
        "year": year,
        "distance_km": pd.NA,
        "flown_distance_km": pd.NA,
        "duration_min": pd.NA,
        "initial_mass_kg": pd.NA,
        "final_mass_kg": pd.NA,
        "oew_kg": 0.0,
        "passenger_payload_kg": 0.0,
        "cargo_payload_kg": 0.0,
        "estimated_block_fuel_kg": 0.0,
        "mass_estimation_method": "not_estimated",
        "fuel_kg": 0.0,
        "energy_mwh": 0.0,
        "co2_kg": 0.0,
        "h2o_kg": 0.0,
        "nox_kg": 0.0,
        "co_kg": 0.0,
        "hc_kg": 0.0,
        "soot_kg": 0.0,
        "sox_kg": 0.0,
        "estimation_mode": "openap_synthetic_mission",
        "quality_flags": "|".join(sorted(quality_flags)),
    }


def estimate_trip_fuel_and_emissions(
    flight_row: pd.Series,
    backend: OpenAPFuelEmissionBackend,
    config: OpenAPFuelConfig,
    application_name: str = "passenger",
) -> dict[str, object]:
    raw_aircraft_type = str(
        _first_value(flight_row, ("aircraft_type", "typecode", "raw_aircraft_type"), default="")
    ).upper()
    mapping = map_to_openap_type(raw_aircraft_type)
    quality_flags: set[str] = set()
    if mapping.mapping_status == "missing":
        quality_flags.add("missing_aircraft_type")
    if mapping.mapping_status == "unsupported":
        quality_flags.add("unsupported_aircraft_type")
    if mapping.mapping_status == "fallback":
        quality_flags.add("fallback_aircraft_type")

    distance_km, distance_flags = _distance_from_row(flight_row)
    quality_flags.update(distance_flags)
    if not mapping.openap_type or distance_km is None or distance_km <= 0.0:
        return _empty_result(
            flight_row=flight_row,
            mapping=mapping,
            quality_flags=quality_flags,
        )

    mission_profile = generate_synthetic_mission_profile(distance_km, mapping.openap_type, config)
    if mission_profile.get("profile_quality_flag", pd.Series(dtype=str)).astype(str).ne("").any():
        quality_flags.add("short_route_adjusted_profile")

    flown_distance = distance_km * config.route_extension_factor
    mass_estimate = backend.estimate_initial_mass_from_context(
        openap_type=mapping.openap_type,
        flight_row=flight_row,
        distance_km=distance_km,
        flown_distance_km=flown_distance,
        application_name=application_name,
    )
    current_mass = mass_estimate.initial_mass_kg
    total_fuel = 0.0
    for _, profile_row in mission_profile.iterrows():
        fuel_flow = backend.fuel_flow_kg_per_s(
            mapping.openap_type,
            current_mass,
            float(profile_row["tas_kt"]),
            float(profile_row["alt_ft"]),
            float(profile_row["vs_fpm"]),
        )
        quality_flags.update(backend.last_quality_flags)
        step_fuel = max(fuel_flow * float(profile_row["delta_t_seconds"]), 0.0)
        if current_mass - step_fuel < mass_estimate.min_mass_kg:
            step_fuel = max(current_mass - mass_estimate.min_mass_kg, 0.0)
            quality_flags.add("minimum_mass_reached")
        current_mass -= step_fuel
        total_fuel += step_fuel

    emissions = backend.estimate_emissions(mapping.openap_type, total_fuel)
    if emissions.get("emission_quality_flag") == "emission_fallback_co2_only":
        quality_flags.add("emission_fallback_co2_only")

    date, year = _date_and_year(flight_row)
    origin = str(_first_value(flight_row, ("origin", "origin_airport"), default="")).upper()
    destination = str(
        _first_value(flight_row, ("destination", "destination_airport"), default="")
    ).upper()
    duration_min = float(mission_profile["delta_t_seconds"].sum()) / 60.0

    return {
        "flight_id": _first_value(flight_row, ("flight_id", "callsign"), default=""),
        "aircraft_id": _first_value(flight_row, ("icao24", "aircraft_id"), default=""),
        "registration": _first_value(flight_row, ("registration",), default=""),
        "operator_name": _first_value(flight_row, ("operator_name", "operator"), default=""),
        "raw_aircraft_type": mapping.raw_type,
        "openap_type": mapping.openap_type,
        "mapping_status": mapping.mapping_status,
        "mapping_note": mapping.mapping_note,
        "origin": origin,
        "destination": destination,
        "route": f"{origin}-{destination}" if origin and destination else "",
        "date": date,
        "year": year,
        "distance_km": distance_km,
        "flown_distance_km": flown_distance,
        "duration_min": duration_min,
        "initial_mass_kg": mass_estimate.initial_mass_kg,
        "final_mass_kg": current_mass,
        "oew_kg": mass_estimate.oew_kg,
        "passenger_payload_kg": mass_estimate.passenger_payload_kg,
        "cargo_payload_kg": mass_estimate.cargo_payload_kg,
        "estimated_block_fuel_kg": mass_estimate.estimated_block_fuel_kg,
        "mass_estimation_method": mass_estimate.mass_estimation_method,
        "fuel_kg": total_fuel,
        "energy_mwh": backend.estimate_energy_mwh(total_fuel),
        "co2_kg": emissions["co2_kg"],
        "h2o_kg": emissions["h2o_kg"],
        "nox_kg": emissions["nox_kg"],
        "co_kg": emissions["co_kg"],
        "hc_kg": emissions["hc_kg"],
        "soot_kg": emissions["soot_kg"],
        "sox_kg": emissions["sox_kg"],
        "estimation_mode": "openap_synthetic_mission",
        "quality_flags": "|".join(sorted(quality_flags)),
    }


def estimate_trajectory_fuel_and_emissions(
    trajectory_df: pd.DataFrame,
    backend: OpenAPFuelEmissionBackend,
    config: OpenAPFuelConfig,
) -> pd.DataFrame:
    if trajectory_df.empty or "flight_id" not in trajectory_df.columns:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    rows: list[dict[str, object]] = []
    for _, group in trajectory_df.groupby("flight_id", dropna=False):
        ordered = group.copy()
        ordered["timestamp"] = pd.to_datetime(ordered["timestamp"], errors="coerce")
        ordered = ordered.dropna(subset=["timestamp"]).sort_values("timestamp")
        if len(ordered) < 2:
            continue
        representative = ordered.iloc[0].copy()
        mapping = map_to_openap_type(
            str(_first_value(representative, ("aircraft_type", "typecode"), default=""))
        )
        if not mapping.openap_type:
            rows.append(
                _empty_result(
                    flight_row=representative,
                    mapping=mapping,
                    quality_flags={f"{mapping.mapping_status}_aircraft_type"},
                )
            )
            continue
        mass = backend.estimate_initial_mass(mapping.openap_type)
        min_mass = backend.estimate_min_mass(mapping.openap_type)
        fuel = 0.0
        for (_, previous), (_, current) in zip(
            ordered.iloc[:-1].iterrows(),
            ordered.iloc[1:].iterrows(),
            strict=False,
        ):
            delta_t = max((current["timestamp"] - previous["timestamp"]).total_seconds(), 0.0)
            if delta_t <= 0.0:
                continue
            tas = float(_first_value(current, ("tas_kt", "velocity", "groundspeed"), default=250.0))
            altitude = float(
                _first_value(current, ("alt_ft", "baroaltitude", "geoaltitude"), default=0.0)
            )
            vertical_rate = float(_first_value(current, ("vertical_rate", "vs_fpm"), default=0.0))
            flow = backend.fuel_flow_kg_per_s(
                mapping.openap_type,
                mass,
                tas,
                altitude,
                vertical_rate,
            )
            step_fuel = max(flow * delta_t, 0.0)
            if mass - step_fuel < min_mass:
                step_fuel = max(mass - min_mass, 0.0)
            fuel += step_fuel
            mass -= step_fuel
        emissions = backend.estimate_emissions(mapping.openap_type, fuel)
        result = estimate_trip_fuel_and_emissions(representative, backend, config)
        result.update(
            {
                "fuel_kg": fuel,
                "energy_mwh": backend.estimate_energy_mwh(fuel),
                "co2_kg": emissions["co2_kg"],
                "h2o_kg": emissions["h2o_kg"],
                "nox_kg": emissions["nox_kg"],
                "co_kg": emissions["co_kg"],
                "hc_kg": emissions["hc_kg"],
                "soot_kg": emissions["soot_kg"],
                "sox_kg": emissions["sox_kg"],
                "final_mass_kg": mass,
                "estimation_mode": "openap_trajectory",
            }
        )
        rows.append(result)
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, pd.NA)
    return numerator / denominator


def _haul_segment(distance_km: float) -> str:
    if distance_km < 1500.0:
        return "short"
    if distance_km <= 4000.0:
        return "medium"
    return "long"


def _summary_by(flight_results: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if flight_results.empty:
        return pd.DataFrame(columns=group_columns)
    valid = flight_results.loc[pd.to_numeric(flight_results["fuel_kg"], errors="coerce") > 0].copy()
    if valid.empty:
        return pd.DataFrame(columns=group_columns)
    grouped = valid.groupby(group_columns, dropna=False).agg(
        number_of_trips=("flight_id", "count"),
        total_distance_km=("distance_km", "sum"),
        total_fuel_kg=("fuel_kg", "sum"),
        total_energy_mwh=("energy_mwh", "sum"),
        total_co2_kg=("co2_kg", "sum"),
        total_nox_kg=("nox_kg", "sum"),
        average_flight_distance_km=("distance_km", "mean"),
        average_fuel_kg_per_flight=("fuel_kg", "mean"),
    )
    summary = grouped.reset_index()
    summary["fuel_kg_per_km"] = _safe_ratio(
        summary["total_fuel_kg"],
        summary["total_distance_km"],
    )
    summary["energy_mwh_per_km"] = _safe_ratio(
        summary["total_energy_mwh"],
        summary["total_distance_km"],
    )
    summary["co2_kg_per_km"] = _safe_ratio(
        summary["total_co2_kg"],
        summary["total_distance_km"],
    )
    return summary


def build_openap_activity_profiles(flight_results: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "aircraft_id",
        "registration",
        "operator_name",
        "raw_aircraft_type",
        "openap_type",
        "year",
    ]
    available_group_columns = [
        column for column in group_columns if column in flight_results.columns
    ]
    by_aircraft = _summary_by(flight_results, available_group_columns)
    if by_aircraft.empty:
        return pd.DataFrame()
    profiles = by_aircraft.rename(
        columns={
            "aircraft_id": "icao24",
            "raw_aircraft_type": "aircraft_type",
        }
    ).copy()
    profiles["typecode"] = profiles["aircraft_type"]
    profiles["segment"] = profiles["average_flight_distance_km"].map(_haul_segment)
    profiles["annual_flights_base"] = profiles["number_of_trips"]
    profiles["annual_distance_km_base"] = profiles["total_distance_km"]
    profiles["mean_stage_length_km_base"] = profiles["average_flight_distance_km"]
    profiles["baseline_energy_demand"] = profiles["total_energy_mwh"] * 1000.0
    profiles["fuel_burn_per_year_base"] = profiles["total_fuel_kg"]
    profiles["activity_assignment_method"] = "openap_type"
    return profiles


def merge_openap_activity_profiles(
    existing_profiles: pd.DataFrame,
    openap_profiles: pd.DataFrame,
) -> pd.DataFrame:
    if openap_profiles.empty:
        return existing_profiles.copy()
    if existing_profiles.empty:
        return openap_profiles.copy()

    merged = existing_profiles.copy()
    for column in openap_profiles.columns:
        if column not in merged.columns:
            merged[column] = pd.NA

    numeric_columns = [
        "number_of_trips",
        "total_distance_km",
        "total_fuel_kg",
        "total_energy_mwh",
        "total_co2_kg",
        "total_nox_kg",
        "fuel_kg_per_km",
        "energy_mwh_per_km",
        "co2_kg_per_km",
        "average_flight_distance_km",
        "average_fuel_kg_per_flight",
        "annual_flights_base",
        "annual_distance_km_base",
        "mean_stage_length_km_base",
        "baseline_energy_demand",
        "fuel_burn_per_year_base",
    ]

    def _fill_from_lookup(key_column: str) -> None:
        if key_column not in openap_profiles.columns or key_column not in merged.columns:
            return
        lookup = (
            openap_profiles.loc[openap_profiles[key_column].astype(str).str.strip() != "",]
            .drop_duplicates(subset=[key_column], keep="first")
            .set_index(key_column)
        )
        if lookup.empty:
            return
        for column in openap_profiles.columns:
            if column not in lookup.columns:
                continue
            mapped = merged[key_column].map(lookup[column])
            if column in numeric_columns:
                current = pd.to_numeric(merged[column], errors="coerce")
                fill_mask = current.isna() | current.eq(0.0)
            else:
                fill_mask = merged[column].isna() | merged[column].astype(str).str.strip().eq("")
            merged.loc[fill_mask, column] = mapped.loc[fill_mask]

    for key_column in ("registration", "icao24", "aircraft_type"):
        _fill_from_lookup(key_column)

    missing_types = set(openap_profiles["aircraft_type"].astype(str)) - set(
        merged.get("aircraft_type", pd.Series(dtype=str)).astype(str)
    )
    if missing_types:
        merged = pd.concat(
            [merged, openap_profiles.loc[openap_profiles["aircraft_type"].isin(missing_types)]],
            ignore_index=True,
        )
    return merged.reset_index(drop=True)


def build_mapping_log(flight_results: pd.DataFrame) -> pd.DataFrame:
    if flight_results.empty:
        return pd.DataFrame(
            columns=["raw_aircraft_type", "openap_type", "mapping_status", "mapping_note", "count"]
        )
    return (
        flight_results.groupby(
            ["raw_aircraft_type", "openap_type", "mapping_status", "mapping_note"],
            dropna=False,
        )
        .size()
        .reset_index(name="count")
    )


def build_validation_report(flight_results: pd.DataFrame) -> str:
    total = len(flight_results)
    processed = int((pd.to_numeric(flight_results.get("fuel_kg"), errors="coerce") > 0).sum())
    skipped = total - processed
    mapping_counts = flight_results.get("mapping_status", pd.Series(dtype=str)).value_counts()
    unsupported = flight_results.loc[
        flight_results.get("mapping_status", pd.Series(dtype=str)).eq("unsupported")
    ]
    valid = flight_results.loc[pd.to_numeric(flight_results.get("fuel_kg"), errors="coerce") > 0]

    lines = [
        "OpenAP aviation fuel/emissions validation report",
        f"flights_processed: {processed}",
        f"flights_skipped: {skipped}",
        f"exact_aircraft_mappings: {int(mapping_counts.get('exact', 0))}",
        f"fallback_aircraft_mappings: {int(mapping_counts.get('fallback', 0))}",
        f"unsupported_aircraft_mappings: {int(mapping_counts.get('unsupported', 0))}",
        f"total_fuel_kg: {float(valid.get('fuel_kg', pd.Series(dtype=float)).sum()):.3f}",
        f"total_energy_mwh: {float(valid.get('energy_mwh', pd.Series(dtype=float)).sum()):.6f}",
        f"total_co2_kg: {float(valid.get('co2_kg', pd.Series(dtype=float)).sum()):.3f}",
    ]
    if not unsupported.empty:
        top = unsupported["raw_aircraft_type"].value_counts().head(10)
        lines.append("top_unsupported_aircraft_types:")
        lines.extend([f"  {aircraft_type}: {count}" for aircraft_type, count in top.items()])
    if not valid.empty:
        type_summary = _summary_by(valid, ["raw_aircraft_type", "openap_type"])
        lines.append("fuel_kg_per_km_by_aircraft_type:")
        for row in type_summary.itertuples(index=False):
            lines.append(
                f"  {row.raw_aircraft_type}/{row.openap_type}: "
                f"{float(row.fuel_kg_per_km):.6f} kg/km, "
                f"{float(row.average_fuel_kg_per_flight):.3f} kg/flight"
            )

        outlier_count = int(
            (
                (pd.to_numeric(valid["fuel_kg"], errors="coerce") <= 0)
                | (pd.to_numeric(valid["distance_km"], errors="coerce") <= 0)
                | (pd.to_numeric(valid["duration_min"], errors="coerce") <= 0)
                | (
                    pd.to_numeric(valid["final_mass_kg"], errors="coerce")
                    > pd.to_numeric(valid["initial_mass_kg"], errors="coerce")
                )
            ).sum()
        )
        lines.append(f"sanity_warnings: {outlier_count}")
    return "\n".join(lines) + "\n"


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def _fill_from_lookup(
    prepared: pd.DataFrame,
    *,
    lookup: pd.DataFrame,
    key_column: str,
    value_columns: list[str],
) -> pd.DataFrame:
    if key_column not in prepared.columns or key_column not in lookup.columns:
        return prepared
    keyed = (
        lookup.loc[lookup[key_column].astype(str).str.strip().ne("")]
        .drop_duplicates(subset=[key_column], keep="first")
        .set_index(key_column)
    )
    if keyed.empty:
        return prepared
    for column in value_columns:
        if column not in keyed.columns:
            continue
        if column not in prepared.columns:
            prepared[column] = pd.NA
        mapped = prepared[key_column].map(keyed[column])
        prepared[column] = prepared[column].where(~_blank_mask(prepared[column]), mapped)
    return prepared


def _merge_stock_context(
    prepared: pd.DataFrame,
    fleet_stock_path: str | Path | None,
) -> pd.DataFrame:
    if fleet_stock_path is None or not Path(fleet_stock_path).exists():
        return prepared
    stock = AviationStockCleaner().clean(fleet_stock_path)
    value_columns = [
        "operator_name",
        "operator_country",
        "current_technology",
        "range_km",
        "seat_total",
        "segment",
        "config_type",
    ]
    lookup_columns = ["registration", "icao24", *value_columns]
    stock_lookup = stock[[column for column in lookup_columns if column in stock.columns]].copy()
    for key_column in ("registration", "icao24"):
        prepared = _fill_from_lookup(
            prepared,
            lookup=stock_lookup,
            key_column=key_column,
            value_columns=value_columns,
        )
    return prepared


def _merge_technology_context(
    prepared: pd.DataFrame,
    technology_catalog_path: str | Path | None,
) -> pd.DataFrame:
    if (
        technology_catalog_path is None
        or not Path(technology_catalog_path).exists()
        or "current_technology" not in prepared.columns
    ):
        return prepared
    technology = pd.read_csv(technology_catalog_path)
    if "technology_name" not in technology.columns:
        return prepared
    technology = technology.drop_duplicates(subset=["technology_name"], keep="first")
    technology = technology.add_prefix("technology_").rename(
        columns={"technology_technology_name": "current_technology"},
    )
    return prepared.merge(technology, on="current_technology", how="left")


def _row_years(prepared: pd.DataFrame) -> pd.Series:
    if "year" in prepared.columns:
        years = pd.to_numeric(prepared["year"], errors="coerce")
    else:
        years = pd.Series(pd.NA, index=prepared.index, dtype="object")
    if years.notna().all():
        return years.astype("Int64")

    for column in ("day", "date", "firstseen", "timestamp"):
        if column not in prepared.columns:
            continue
        parsed = pd.to_datetime(prepared[column], errors="coerce")
        years = years.fillna(parsed.dt.year)
    return years.astype("Int64")


def _merge_scenario_context(
    prepared: pd.DataFrame,
    scenario_table_path: str | Path | None,
) -> pd.DataFrame:
    if scenario_table_path is None or not Path(scenario_table_path).exists():
        return prepared
    scenario = pd.read_csv(scenario_table_path)
    year_columns = [column for column in scenario.columns if str(column).isdigit()]
    if not year_columns or "variable_name" not in scenario.columns:
        return prepared

    target_variables = {
        "economy_occupancy",
        "business_occupancy",
        "first_occupancy",
        "load_factor",
    }
    long = scenario.loc[scenario["variable_name"].isin(target_variables)].melt(
        id_vars=["variable_name", "operator_name"],
        value_vars=year_columns,
        var_name="year",
        value_name="value",
    )
    if long.empty:
        return prepared
    long["operator_name"] = long["operator_name"].fillna("").astype(str).str.strip()
    long["year"] = pd.to_numeric(long["year"], errors="coerce").astype("Int64")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")

    prepared = prepared.copy()
    prepared["year"] = _row_years(prepared)
    operator_series = prepared.get("operator_name", pd.Series("", index=prepared.index))
    lookup_frame = pd.DataFrame(
        {
            "operator_name": operator_series.fillna("").astype(str).str.strip(),
            "year": prepared["year"],
        },
        index=prepared.index,
    )
    for variable_name in target_variables:
        variable_lookup = (
            long.loc[long["variable_name"].eq(variable_name)]
            .dropna(subset=["value"])
            .drop_duplicates(subset=["operator_name", "year"], keep="first")
            .set_index(["operator_name", "year"])["value"]
        )
        if variable_lookup.empty:
            continue
        keys = pd.MultiIndex.from_frame(lookup_frame[["operator_name", "year"]])
        values = pd.Series(variable_lookup.reindex(keys).to_numpy(), index=prepared.index)
        fallback_lookup = (
            long.loc[long["variable_name"].eq(variable_name)]
            .dropna(subset=["value"])
            .sort_values("year")
            .drop_duplicates(subset=["operator_name"], keep="first")
            .set_index("operator_name")["value"]
        )
        if not fallback_lookup.empty:
            fallback_values = lookup_frame["operator_name"].map(fallback_lookup)
            values = values.fillna(fallback_values)
        prepared[variable_name] = pd.Series(
            values.to_numpy(),
            index=prepared.index,
        )
    return prepared


def prepare_trip_level_flights(
    *,
    processed_flightlist_path: str | Path,
    airport_metadata_path: str | Path,
    aircraft_db_processed_path: str | Path | None = None,
    fleet_stock_path: str | Path | None = None,
    technology_catalog_path: str | Path | None = None,
    scenario_table_path: str | Path | None = None,
) -> pd.DataFrame:
    flights = read_parquet_compatible(processed_flightlist_path)
    airports = load_airport_metadata(airport_metadata_path)
    airport_lookup = airports.set_index("airport_code")[
        ["latitude_deg", "longitude_deg", "country"]
    ]
    prepared = flights.copy()
    prepared["origin"] = prepared["origin"].astype(str).str.upper().str.strip()
    prepared["destination"] = prepared["destination"].astype(str).str.upper().str.strip()
    prepared = prepared.join(airport_lookup.add_prefix("origin_"), on="origin")
    prepared = prepared.join(airport_lookup.add_prefix("destination_"), on="destination")
    prepared = prepared.dropna(
        subset=[
            "origin_latitude_deg",
            "origin_longitude_deg",
            "destination_latitude_deg",
            "destination_longitude_deg",
        ],
    ).copy()
    computed_distance = prepared.apply(
        lambda row: great_circle_distance_km(
            float(row["origin_latitude_deg"]),
            float(row["origin_longitude_deg"]),
            float(row["destination_latitude_deg"]),
            float(row["destination_longitude_deg"]),
        ),
        axis=1,
    )
    if "distance_km" in prepared.columns:
        prepared["distance_km"] = pd.to_numeric(prepared["distance_km"], errors="coerce")
        prepared["distance_km"] = prepared["distance_km"].where(
            prepared["distance_km"] > 0.0,
            computed_distance,
        )
    else:
        prepared["distance_km"] = computed_distance
    if "aircraft_type" in prepared.columns:
        prepared["aircraft_type"] = prepared["aircraft_type"].astype(str).str.upper().str.strip()
        if "typecode" in prepared.columns:
            fallback_type = prepared["typecode"].astype(str).str.upper().str.strip()
            prepared["aircraft_type"] = prepared["aircraft_type"].where(
                prepared["aircraft_type"].ne(""),
                fallback_type,
            )
    elif "typecode" in prepared.columns:
        prepared["aircraft_type"] = prepared["typecode"].astype(str).str.upper().str.strip()
    else:
        prepared["aircraft_type"] = ""
    prepared["flight_id"] = prepared.apply(
        lambda row: str(row.get("callsign", "")).strip()
        or (
            f"{row.get('icao24', '')}-{row.get('origin', '')}-"
            f"{row.get('destination', '')}-{row.name}"
        ),
        axis=1,
    )

    if aircraft_db_processed_path is not None and Path(aircraft_db_processed_path).exists():
        aircraft_db = pd.read_csv(aircraft_db_processed_path)
        if {"registration", "icao24", "operator"}.issubset(aircraft_db.columns) and {
            "registration",
            "icao24",
        }.issubset(prepared.columns):
            metadata = aircraft_db.drop_duplicates(subset=["registration", "icao24"], keep="first")
            prepared = prepared.merge(
                metadata[["registration", "icao24", "operator"]],
                on=["registration", "icao24"],
                how="left",
            )
            prepared = prepared.rename(columns={"operator": "operator_name"})
    if "operator_name" not in prepared.columns:
        prepared["operator_name"] = ""
    prepared = _merge_stock_context(prepared, fleet_stock_path)
    prepared = _merge_technology_context(prepared, technology_catalog_path)
    prepared = _merge_scenario_context(prepared, scenario_table_path)
    return prepared.reset_index(drop=True)


def _write_openap_outputs(
    *,
    flight_results: pd.DataFrame,
    output_dir: str | Path,
    existing_activity_profiles_path: str | Path | None = None,
) -> OpenAPFuelOutputs:
    aircraft_type_summary = _summary_by(
        flight_results,
        ["raw_aircraft_type", "openap_type", "year"],
    )
    route_summary = _summary_by(
        flight_results,
        ["origin", "destination", "route", "raw_aircraft_type", "openap_type", "year"],
    )
    openap_activity_profiles = build_openap_activity_profiles(flight_results)
    if (
        existing_activity_profiles_path is not None
        and Path(existing_activity_profiles_path).exists()
    ):
        existing_activity_profiles = pd.read_csv(existing_activity_profiles_path)
        activity_profiles = merge_openap_activity_profiles(
            existing_activity_profiles,
            openap_activity_profiles,
        )
    else:
        activity_profiles = openap_activity_profiles
    mapping_log = build_mapping_log(flight_results)
    validation_report = build_validation_report(flight_results)

    target_dir = Path(output_dir)
    ensure_parent_dir(target_dir / "openap_flight_fuel_emissions.csv")
    flight_results.to_csv(target_dir / "openap_flight_fuel_emissions.csv", index=False)
    aircraft_type_summary.to_csv(target_dir / "openap_aircraft_type_summary.csv", index=False)
    route_summary.to_csv(target_dir / "openap_route_summary.csv", index=False)
    mapping_log.to_csv(target_dir / "openap_aircraft_type_mapping_log.csv", index=False)
    activity_profiles.to_csv(target_dir / "aviation_activity_profiles.csv", index=False)
    (target_dir / "openap_validation_report.txt").write_text(
        validation_report,
        encoding="utf-8",
    )
    return OpenAPFuelOutputs(
        flight_results=flight_results,
        aircraft_type_summary=aircraft_type_summary,
        route_summary=route_summary,
        activity_profiles=activity_profiles,
        mapping_log=mapping_log,
        validation_report=validation_report,
    )


def run_openap_trip_estimation(
    *,
    processed_flightlist_path: str | Path,
    airport_metadata_path: str | Path,
    output_dir: str | Path,
    aircraft_db_processed_path: str | Path | None = None,
    fleet_stock_path: str | Path | None = None,
    technology_catalog_path: str | Path | None = None,
    scenario_table_path: str | Path | None = None,
    application_name: str = "passenger",
    config: OpenAPFuelConfig | None = None,
    existing_activity_profiles_path: str | Path | None = None,
) -> OpenAPFuelOutputs:
    fuel_config = config or OpenAPFuelConfig()
    backend = OpenAPFuelEmissionBackend(fuel_config)
    flights = prepare_trip_level_flights(
        processed_flightlist_path=processed_flightlist_path,
        airport_metadata_path=airport_metadata_path,
        aircraft_db_processed_path=aircraft_db_processed_path,
        fleet_stock_path=fleet_stock_path,
        technology_catalog_path=technology_catalog_path,
        scenario_table_path=scenario_table_path,
    )
    result_rows = [
        estimate_trip_fuel_and_emissions(row, backend, fuel_config, application_name)
        for _, row in flights.iterrows()
    ]
    flight_results = pd.DataFrame(result_rows, columns=RESULT_COLUMNS)
    return _write_openap_outputs(
        flight_results=flight_results,
        output_dir=output_dir,
        existing_activity_profiles_path=existing_activity_profiles_path,
    )


def run_openap_trajectory_estimation(
    *,
    trajectory_input_path: str | Path,
    output_dir: str | Path,
    config: OpenAPFuelConfig | None = None,
    existing_activity_profiles_path: str | Path | None = None,
) -> OpenAPFuelOutputs:
    fuel_config = config or OpenAPFuelConfig()
    backend = OpenAPFuelEmissionBackend(fuel_config)
    trajectory_points = read_parquet_compatible(trajectory_input_path)
    flight_results = estimate_trajectory_fuel_and_emissions(
        trajectory_points,
        backend,
        fuel_config,
    )
    return _write_openap_outputs(
        flight_results=flight_results,
        output_dir=output_dir,
        existing_activity_profiles_path=existing_activity_profiles_path,
    )
