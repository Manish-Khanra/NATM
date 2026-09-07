"""Disaggregates annual per-aircraft/vessel energy totals into an hourly
timeseries, using a real-data-derived hour-of-week activity shape.

The simulation itself only computes one energy total per asset per
simulated year (see `Fleet.update_operation_metrics`) -- there is no native
hourly signal in the model. This module derives a real hour-of-week
activity pattern from historical OpenSky flight timestamps (aviation) or
Global Fishing Watch AIS port-visit timestamps (maritime), then spreads each
asset-year's annual energy total across that year's real calendar hours in
proportion to that pattern. The result differentiates by aircraft/vessel,
year, energy type (primary/secondary carrier), and region (hub airport/port,
via `main_hub_base`).

Output is Parquet (not CSV): a full per-aircraft hourly breakdown is large
(hundreds of millions of rows for the full real fleet across 2025-2050), and
Parquet keeps this both compact and fast to query.
"""
from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HOURS_PER_WEEK = 168


def _read_maybe_double_gzip_csv(path: Path, usecols: list[str]) -> pd.DataFrame:
    """Reads a .csv.gz file, transparently handling the double-gzip archives
    found under data/archive/OpenSkyNetwork/ (each file was gzipped twice)."""
    import io

    raw = path.read_bytes()
    decompressed = gzip.decompress(raw)
    if decompressed[:2] == b"\x1f\x8b":
        decompressed = gzip.decompress(decompressed)
    return pd.read_csv(io.BytesIO(decompressed), usecols=usecols)


def aviation_weekly_activity_shape(sample_paths: list[Path]) -> np.ndarray:
    """Derives a real 168-length (day_of_week*24+hour_of_day) activity shape
    from real OpenSky flight departure timestamps, normalized to sum to 1.0.

    Samples a handful of representative months (not all 24 archived files)
    to keep this tractable -- real, just not exhaustive.
    """
    counts = np.zeros(HOURS_PER_WEEK, dtype=np.float64)
    for path in sample_paths:
        frame = _read_maybe_double_gzip_csv(path, usecols=["firstseen"])
        timestamps = pd.to_datetime(frame["firstseen"], utc=True, errors="coerce").dropna()
        slot = timestamps.dt.dayofweek.to_numpy() * 24 + timestamps.dt.hour.to_numpy()
        counts += np.bincount(slot, minlength=HOURS_PER_WEEK)[:HOURS_PER_WEEK]
    total = counts.sum()
    if total <= 0:
        raise ValueError("No real timestamps found in sample_paths; cannot derive activity shape")
    return counts / total


def maritime_weekly_activity_shape(port_visits_path: Path) -> np.ndarray:
    """Derives a real 168-length activity shape from real AIS port-visit
    start timestamps (Global Fishing Watch data), normalized to sum to 1.0."""
    frame = pd.read_csv(port_visits_path, usecols=["start"])
    timestamps = pd.to_datetime(frame["start"], utc=True, errors="coerce").dropna()
    slot = timestamps.dt.dayofweek.to_numpy() * 24 + timestamps.dt.hour.to_numpy()
    counts = np.bincount(slot, minlength=HOURS_PER_WEEK)[:HOURS_PER_WEEK].astype(np.float64)
    total = counts.sum()
    if total <= 0:
        raise ValueError(f"No real timestamps found in {port_visits_path}")
    return counts / total


def _hour_weights_for_year(year: int, weekly_shape: np.ndarray) -> np.ndarray:
    """Every real calendar hour of `year`, weighted by the real weekly shape
    at that hour's (day_of_week, hour_of_day), normalized to sum to 1.0 over
    the year (so multiplying by an annual total redistributes it exactly)."""
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    slot = hours.dayofweek.to_numpy() * 24 + hours.hour.to_numpy()
    weights = weekly_shape[slot]
    return hours, weights / weights.sum()


def expand_to_hourly(
    aircraft_csv: Path,
    weekly_shape: np.ndarray,
    output_path: Path,
    *,
    hub_column_priority: tuple[str, ...] = ("main_hub_base", "main_hub"),
    id_column: str = "aircraft_id",
) -> int:
    """Reads a results folder's aircraft.csv and writes an hourly-expanded
    Parquet file: one row per (asset, year, hour, energy_type), with region
    = the asset's real hub. Returns the number of rows written.

    Processes one simulated year at a time to keep memory bounded -- a full
    real fleet across the 2025-2050 horizon is far too large to hold as one
    in-memory frame.
    """
    aircraft = pd.read_csv(aircraft_csv)
    hub_column = next((c for c in hub_column_priority if c in aircraft.columns), None)
    if hub_column is None:
        raise ValueError(f"None of {hub_column_priority} found in {aircraft_csv}")

    required = {
        id_column,
        "operator_name",
        "year",
        "primary_energy_carrier",
        "primary_energy_consumption",
        "secondary_energy_carrier",
        "secondary_energy_consumption",
        hub_column,
    }
    missing = required - set(aircraft.columns)
    if missing:
        raise ValueError(f"{aircraft_csv} is missing required columns: {sorted(missing)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("timestamp", pa.timestamp("s", tz="UTC")),
            (id_column, aircraft[id_column].dtype.name if id_column in aircraft else pa.int64()),
            ("operator_name", pa.string()),
            ("year", pa.int32()),
            ("region", pa.string()),
            ("energy_type", pa.string()),
            ("energy_kwh", pa.float64()),
        ],
    )
    writer = pq.ParquetWriter(output_path, schema)
    total_rows = 0
    try:
        for year, year_frame in aircraft.groupby("year"):
            hours, hour_weights = _hour_weights_for_year(int(year), weekly_shape)

            year_frame = year_frame.copy()
            year_frame["region"] = (
                year_frame[hub_column].fillna("").astype(str).str.strip()
            )
            year_frame.loc[year_frame["region"].eq(""), "region"] = "unknown"

            blocks: list[pd.DataFrame] = []
            for _energy_role, carrier_col, quantity_col in (
                ("primary", "primary_energy_carrier", "primary_energy_consumption"),
                ("secondary", "secondary_energy_carrier", "secondary_energy_consumption"),
            ):
                rows = year_frame.loc[
                    pd.to_numeric(year_frame[quantity_col], errors="coerce").fillna(0.0) > 0.0,
                    [id_column, "operator_name", "region", carrier_col, quantity_col],
                ].copy()
                if rows.empty:
                    continue
                rows["energy_type"] = (
                    rows[carrier_col].fillna("").astype(str).str.strip().str.lower()
                )
                rows = rows.loc[~rows["energy_type"].isin(["", "none"])]
                if rows.empty:
                    continue
                annual = pd.to_numeric(rows[quantity_col], errors="coerce").fillna(0.0).to_numpy()

                # Outer product: (n_assets, n_hours) = annual[:, None] * hour_weights[None, :]
                hourly_matrix = annual[:, None] * hour_weights[None, :]
                expanded = pd.DataFrame(
                    hourly_matrix,
                    index=pd.MultiIndex.from_frame(
                        rows[[id_column, "operator_name", "region", "energy_type"]],
                    ),
                    columns=hours,
                ).stack()
                expanded.index.set_names("timestamp", level=-1, inplace=True)
                expanded = expanded.rename("energy_kwh").reset_index()
                expanded["year"] = int(year)
                blocks.append(expanded)

            if not blocks:
                continue
            year_hourly = pd.concat(blocks, ignore_index=True)
            year_hourly = year_hourly[
                [
                    "timestamp",
                    id_column,
                    "operator_name",
                    "year",
                    "region",
                    "energy_type",
                    "energy_kwh",
                ]
            ]
            table = pa.Table.from_pandas(year_hourly, schema=schema, preserve_index=False)
            writer.write_table(table)
            total_rows += len(year_hourly)
    finally:
        writer.close()
    return total_rows
