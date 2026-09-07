from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from navaero_transition_model.postprocessing.hourly_timeseries import (
    aviation_weekly_activity_shape,
    expand_to_hourly,
    maritime_weekly_activity_shape,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

AVIATION_SHAPE_CACHE = (
    REPO_ROOT / "data" / "processed" / "aviation" / "aviation_weekly_activity_shape.npy"
)
MARITIME_SHAPE_CACHE = (
    REPO_ROOT / "data" / "processed" / "maritime" / "maritime_weekly_activity_shape.npy"
)

# A representative sample of real OpenSky flightlist months (not all 24
# archived files, which would take much longer to process for the same
# resulting weekly shape).
DEFAULT_AVIATION_SAMPLE = [
    REPO_ROOT / "data" / "archive" / "OpenSkyNetwork" / "flightlist_20220101_20220131.csv.gz",
    REPO_ROOT / "data" / "archive" / "OpenSkyNetwork" / "flightlist_20220401_20220430.csv.gz",
    REPO_ROOT / "data" / "archive" / "OpenSkyNetwork" / "flightlist_20220701_20220731.csv.gz",
    REPO_ROOT / "data" / "archive" / "OpenSkyNetwork" / "flightlist_20221001_20221031.csv.gz",
]
DEFAULT_MARITIME_PORT_VISITS = (
    REPO_ROOT / "data" / "archive" / "maritime" / "AIS" / "gfw_port_visits_2024.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Disaggregate a simulation run's annual per-asset energy totals into an "
            "hourly timeseries (aircraft/vessel, year, energy type, region), using a "
            "real-data-derived hour-of-week activity shape."
        ),
    )
    parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="Simulation result folder containing aircraft.csv.",
    )
    parser.add_argument(
        "--sector",
        choices=("aviation", "maritime"),
        default=None,
        help="Which real activity shape to use. Defaults to auto-detect from "
        "aircraft.csv's sector_name column.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output Parquet path. Defaults to <results>/hourly_energy_timeseries.parquet.",
    )
    parser.add_argument(
        "--refresh-shape-cache",
        action="store_true",
        help="Recompute the real weekly activity shape instead of using the cached .npy.",
    )
    return parser


def _detect_sector(aircraft_csv: Path) -> str:
    import pandas as pd

    sample = pd.read_csv(aircraft_csv, usecols=["sector_name"], nrows=1000)
    sectors = set(sample["sector_name"].dropna().astype(str).str.lower())
    if "maritime" in sectors:
        return "maritime"
    return "aviation"


def _load_or_derive_shape(sector: str, *, refresh: bool) -> np.ndarray:
    if sector == "aviation":
        if AVIATION_SHAPE_CACHE.exists() and not refresh:
            return np.load(AVIATION_SHAPE_CACHE)
        shape = aviation_weekly_activity_shape(DEFAULT_AVIATION_SAMPLE)
        AVIATION_SHAPE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.save(AVIATION_SHAPE_CACHE, shape)
        return shape

    if MARITIME_SHAPE_CACHE.exists() and not refresh:
        return np.load(MARITIME_SHAPE_CACHE)
    shape = maritime_weekly_activity_shape(DEFAULT_MARITIME_PORT_VISITS)
    MARITIME_SHAPE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.save(MARITIME_SHAPE_CACHE, shape)
    return shape


def main() -> int:
    args = build_parser().parse_args()
    aircraft_csv = args.results / "aircraft.csv"
    if not aircraft_csv.exists():
        raise SystemExit(f"{aircraft_csv} not found.")

    sector = args.sector or _detect_sector(aircraft_csv)
    shape = _load_or_derive_shape(sector, refresh=args.refresh_shape_cache)
    output_path = args.output or (args.results / "hourly_energy_timeseries.parquet")

    row_count = expand_to_hourly(aircraft_csv, shape, output_path)
    print(f"Sector: {sector}")
    print(f"Hourly timeseries: {output_path}")
    print(f"Rows written: {row_count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
