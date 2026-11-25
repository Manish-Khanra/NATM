"""Exports 15-minute-resolution electricity demand by airport/port and fuel
type to CSV -- one file per sector, scenarios stacked with a `scenario`
column (a lighter alternative to one Excel workbook per sector with a sheet
per scenario: the xlsx form ran to ~600MB for the passenger sector alone).

The simulation only produces one annual energy total per asset per year (see
navaero_transition_model/postprocessing/hourly_timeseries.py, which does the
same disaggregation at hourly resolution for raw fuel energy). This module:

1. Reuses analysis.cartographic_dashboard.ELECTRICITY_SOURCES to identify
   which rows of aircraft.csv are electricity-derived (e-kerosene, hydrogen,
   hybrid-assist battery, ...) and convert their annual fuel energy to
   electricity via the same default efficiencies used throughout the
   dashboard/notebook.
2. Aggregates that to one annual electricity total per (year, hub, fuel type)
   -- per-airport, not per-aircraft, since that is the requested granularity.
3. Spreads each annual total across that year's real calendar 15-minute
   slots using a REAL, data-derived quarter-hour-of-week activity pattern
   (from OpenSky flight timestamps for aviation, GFW AIS port-visit
   timestamps for maritime -- both have second-level precision, so this is
   a genuine 15-minute pattern, not an even split of an hourly one).
4. Stacks scenarios into one CSV per sector with a `scenario` column
   standing in for what would otherwise be one sheet per scenario,
   restricted to only the years that scenario actually has nonzero
   electricity demand in (scenarios with none at all are omitted and
   reported on stdout instead).

Each row is wide (one row per scenario+timestamp, one column per
hub+fuel-type combination), not long (one row per scenario+timestamp+hub+
fuel-type): the long form would run to ~14 million rows for the passenger
sector's e-kerosene alone (23 years x 35,040 quarter-hours x up to 18
hub/fuel combinations x 8 scenarios stacked). Wide keeps the column count
small (2-18 here) at the cost of one column per hub/fuel-type combination.

Run:  python analysis/export_electricity_15min.py
Out:  data/processed/electricity_15min/{cargo,passenger,maritime_cargo}_electricity_demand_15min.csv
"""

from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.cartographic_dashboard import (  # noqa: E402
    ELECTRICITY_SOURCES,
    RESULTS_ROOT,
    ROOT,
    scenario_sibling_folders,
)

OUTPUT_DIR = ROOT / "data" / "processed" / "electricity_15min"
SLOTS_PER_WEEK = 7 * 24 * 4  # quarter-hours in a week
SLOTS_PER_DAY = 24 * 4

SECTORS = {
    "cargo": {
        "label": "Aviation Cargo",
        "reference_folder": "baseline-cargo-transition-fokush2-risk-neutral",
        "activity": "aviation",
    },
    "passenger": {
        "label": "Aviation Passenger",
        "reference_folder": "baseline-passenger-transition-fokush2-risk-neutral",
        "activity": "aviation",
    },
    "maritime_cargo": {
        "label": "Maritime Cargo",
        "reference_folder": "baseline-maritime-cargo-transition-fokush2-risk-neutral",
        "activity": "maritime",
    },
}


def _read_maybe_double_gzip_csv(path: Path, usecols: list[str]) -> pd.DataFrame:
    raw = path.read_bytes()
    decompressed = gzip.decompress(raw)
    if decompressed[:2] == b"\x1f\x8b":
        decompressed = gzip.decompress(decompressed)
    return pd.read_csv(io.BytesIO(decompressed), usecols=usecols)


def aviation_quarter_hour_shape() -> np.ndarray:
    """Real quarter-hour-of-week activity shape from a sample of OpenSky
    flight departure timestamps (firstseen has second-level precision).
    Samples a representative few months across seasons, mirroring the
    existing hourly module's approach, not all 24 archived files."""
    sample_dir = ROOT / "data" / "archive" / "OpenSkyNetwork"
    sample_files = sorted(sample_dir.glob("flightlist_*.csv.gz"))
    if not sample_files:
        raise FileNotFoundError(f"no OpenSky sample files found under {sample_dir}")
    # January, April, July, October -- one per season, first year available.
    chosen = [f for f in sample_files if f.name.split("_")[1][4:6] in {"01", "04", "07", "10"}][:4]
    if not chosen:
        chosen = sample_files[:4]

    counts = np.zeros(SLOTS_PER_WEEK, dtype=np.float64)
    for path in chosen:
        frame = _read_maybe_double_gzip_csv(path, usecols=["firstseen"])
        timestamps = pd.to_datetime(frame["firstseen"], utc=True, errors="coerce").dropna()
        slot = (
            timestamps.dt.dayofweek.to_numpy() * SLOTS_PER_DAY
            + timestamps.dt.hour.to_numpy() * 4
            + timestamps.dt.minute.to_numpy() // 15
        )
        counts += np.bincount(slot, minlength=SLOTS_PER_WEEK)[:SLOTS_PER_WEEK]
    total = counts.sum()
    if total <= 0:
        raise ValueError("no real timestamps found in the sampled OpenSky files")
    return counts / total


def maritime_quarter_hour_shape() -> np.ndarray:
    """Real quarter-hour-of-week activity shape from GFW AIS port-visit
    start timestamps (second-level precision)."""
    path = ROOT / "data" / "archive" / "maritime" / "AIS" / "gfw_port_visits_2024.csv"
    frame = pd.read_csv(path, usecols=["start"])
    timestamps = pd.to_datetime(frame["start"], utc=True, errors="coerce").dropna()
    slot = (
        timestamps.dt.dayofweek.to_numpy() * SLOTS_PER_DAY
        + timestamps.dt.hour.to_numpy() * 4
        + timestamps.dt.minute.to_numpy() // 15
    )
    counts = np.bincount(slot, minlength=SLOTS_PER_WEEK)[:SLOTS_PER_WEEK].astype(np.float64)
    total = counts.sum()
    if total <= 0:
        raise ValueError(f"no real timestamps found in {path}")
    return counts / total


def _quarter_hours_for_year(year: int, shape: np.ndarray) -> tuple[pd.DatetimeIndex, np.ndarray]:
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    stamps = pd.date_range(start, end, freq="15min", inclusive="left")
    slot = (
        stamps.dayofweek.to_numpy() * SLOTS_PER_DAY
        + stamps.hour.to_numpy() * 4
        + stamps.minute.to_numpy() // 15
    )
    weights = shape[slot]
    return stamps, weights / weights.sum()


def _aviation_hub_names() -> dict[str, str]:
    """ICAO code -> real airport name, from OpenAP's navigation database
    (already a project dependency and the source of the route network
    itself -- see cartographic_dashboard._openap_airport_coordinates, which
    uses the same table for map coordinates). A raw code like "EDDP" or
    "EDDS" is not obviously distinguishable at a glance; this is what makes
    a column header read as "Leipzig-Halle (EDDP)" instead."""
    from openap import nav

    table = pd.read_csv(nav.db_airport, usecols=["icao", "name"])
    return dict(zip(table["icao"].astype(str).str.upper(), table["name"], strict=True))


def hub_display_name(hub: str, activity: str) -> str:
    """A human-readable label for one hub code, by activity type: aviation
    hubs are bare ICAO codes needing a name lookup; maritime hubs are
    already real port names (e.g. "HAMBURG"), just upper-cased in the
    source data, so title-casing is all that is needed."""
    if activity == "aviation":
        name = _AVIATION_HUB_NAMES.get(hub.upper())
        return f"{name} ({hub})" if name else hub
    return hub.title()


_AVIATION_HUB_NAMES = _aviation_hub_names()


def annual_electricity_by_hub(folder: str) -> pd.DataFrame:
    """(year, hub, fuel_label) -> electricity_kwh for one results folder,
    using the same carrier matching and default efficiencies as the
    dashboard/notebook (analysis.cartographic_dashboard.ELECTRICITY_SOURCES)."""
    path = RESULTS_ROOT / folder / "aircraft.csv"
    if not path.exists():
        return pd.DataFrame(columns=["year", "hub", "fuel_label", "electricity_kwh"])

    hub_columns = ("main_hub_base", "main_hub")
    needed = {"year", "primary_energy_carrier", "secondary_energy_carrier"}
    needed |= {"primary_energy_consumption", "secondary_energy_consumption"}
    needed |= set(hub_columns)
    try:
        frame = pd.read_csv(path, usecols=lambda c: c in needed)
    except Exception:
        return pd.DataFrame(columns=["year", "hub", "fuel_label", "electricity_kwh"])
    hub_column = next((c for c in hub_columns if c in frame.columns), None)
    if hub_column is None or "year" not in frame.columns:
        return pd.DataFrame(columns=["year", "hub", "fuel_label", "electricity_kwh"])

    frame["hub"] = frame[hub_column].fillna("").astype(str).str.strip().str.upper()
    frame = frame.loc[frame["hub"].ne("")]

    rows = []
    for source, spec in ELECTRICITY_SOURCES.items():
        carrier_column, field = spec["carrier_column"], spec["field"]
        if carrier_column not in frame.columns or field not in frame.columns:
            continue
        match_value = spec.get("match_value", source)
        matched = frame.loc[
            frame[carrier_column].astype(str).str.strip().str.lower().eq(match_value)
        ]
        if matched.empty:
            continue
        fuel_kwh = pd.to_numeric(matched[field], errors="coerce").fillna(0.0)
        electricity_kwh = fuel_kwh / max(float(spec["efficiency"]), 0.01)
        grouped = electricity_kwh.groupby([matched["year"], matched["hub"]]).sum()
        grouped = grouped.loc[grouped > 0]
        if grouped.empty:
            continue
        block = grouped.reset_index()
        block.columns = ["year", "hub", "electricity_kwh"]
        block["fuel_label"] = spec["label"]
        rows.append(block)
    if not rows:
        return pd.DataFrame(columns=["year", "hub", "fuel_label", "electricity_kwh"])
    return pd.concat(rows, ignore_index=True)


def expand_scenario_to_15min(folder: str, shape: np.ndarray, activity: str) -> pd.DataFrame | None:
    """Wide 15-minute-resolution frame for one scenario: index = timestamp,
    one column per hub+fuel-type, restricted to years with nonzero
    electricity demand. None if the scenario has no electricity demand at
    all."""
    annual = annual_electricity_by_hub(folder)
    if annual.empty:
        return None

    hub_names = annual["hub"].map(lambda hub: hub_display_name(hub, activity))
    annual["column"] = hub_names + " -- " + annual["fuel_label"]
    year_blocks = []
    for year, year_annual in annual.groupby("year"):
        stamps, weights = _quarter_hours_for_year(int(year), shape)
        pivot = year_annual.pivot_table(
            index=[], columns="column", values="electricity_kwh", aggfunc="sum"
        )
        totals = pivot.iloc[0] if not pivot.empty else pd.Series(dtype=float)
        # outer product: (n_slots, n_columns) = weights[:, None] * totals[None, :]
        block = pd.DataFrame(
            weights[:, None] * totals.to_numpy()[None, :],
            index=stamps,
            columns=totals.index,
        )
        year_blocks.append(block)
    combined = pd.concat(year_blocks).sort_index()
    combined.index.name = "timestamp"
    combined = combined.reset_index()
    # Excel has no timezone-aware datetime type. Every timestamp here is UTC
    # (both source activity patterns are derived from UTC-stamped real data),
    # so dropping the tz label loses no information -- it's implicit.
    combined["timestamp"] = combined["timestamp"].dt.tz_localize(None)
    return combined


def export_sector(sector_key: str) -> Path:
    """One CSV per sector (not one Excel workbook with a sheet per scenario):
    a "scenario" column stands in for the sheet split. CSV has no per-file
    row limit the way an Excel sheet does, and is plain text with none of
    xlsx's per-cell/zip-container overhead, so it is both simpler to produce
    for a variable, occasionally very large, row count and noticeably
    lighter on disk for the same data -- the original xlsx output ran to
    ~600MB for the passenger sector alone. Scenarios with no electricity
    demand at all are omitted from the file (there is no clean way to note
    that inside a single numeric table) and reported on stdout instead.
    """
    spec = SECTORS[sector_key]
    shape = (
        aviation_quarter_hour_shape()
        if spec["activity"] == "aviation"
        else maritime_quarter_hour_shape()
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{sector_key}_electricity_demand_15min.csv"

    blocks = []
    skipped = []
    for folder in scenario_sibling_folders(spec["reference_folder"]):
        scenario_name = folder.split("-transition-")[-1]
        frame = expand_scenario_to_15min(folder, shape, spec["activity"])
        if frame is None:
            skipped.append(scenario_name)
            print(f"  {scenario_name}: no electricity demand (omitted)")
            continue
        frame.insert(0, "scenario", scenario_name)
        blocks.append(frame)
        print(f"  {scenario_name}: {len(frame):,} rows, {len(frame.columns) - 2} hub/fuel columns")

    if not blocks:
        pd.DataFrame(columns=["scenario", "timestamp"]).to_csv(output_path, index=False)
        print("  (no scenario in this sector has any electricity demand)")
        return output_path

    # Union of hub/fuel columns across scenarios (they differ -- e.g. one
    # scenario's fleet might adopt e-kerosene at only one of two airports).
    # concat aligns on column name and fills the rest with NaN -> 0.
    combined = pd.concat(blocks, ignore_index=True, sort=False)
    value_columns = [c for c in combined.columns if c not in ("scenario", "timestamp")]
    combined[value_columns] = combined[value_columns].fillna(0.0)
    combined.to_csv(output_path, index=False)
    if skipped:
        print(f"  omitted (no electricity demand): {', '.join(skipped)}")
    return output_path


def main() -> None:
    for sector_key in SECTORS:
        print(f"=== {SECTORS[sector_key]['label']} ===")
        path = export_sector(sector_key)
        print(f"  -> {path}\n")


if __name__ == "__main__":
    main()
