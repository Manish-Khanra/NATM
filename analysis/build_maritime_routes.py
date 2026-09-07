"""Build the maritime sea-route layer used by the cartographic dashboard.

The aviation side of the dashboard has `openap_route_summary.csv` -- a real
origin/destination flight network. The maritime side had no equivalent, so its
map showed ports with no connections at all (and, before that, aviation flight
paths drawn over ship ports).

This derives the maritime equivalent from the AIS voyage record: consecutive
port calls by the same vessel, which is exactly a voyage. Unlike the aviation
arcs, the geometry here follows actual sea lanes computed with `searoute`, so a
Hamburg-Singapore voyage runs through the Channel, Gibraltar and Suez instead
of cutting a great circle across Europe and Asia.

Run:  python analysis/build_maritime_routes.py
Out:  data/processed/maritime/maritime_sea_routes.csv
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VOYAGES_PATH = (
    ROOT / "data" / "archive" / "maritime" / "AIS" / "gfw_route_pairs_2024_with_distances.csv"
)
OUTPUT_PATH = ROOT / "data" / "processed" / "maritime" / "maritime_sea_routes.csv"

# The hubs the maritime model actually bases vessels at, as emitted by
# navaero_transition_model.maritime_preprocessing.hub_assignment.
MODEL_PORTS = {
    "BRAKE",
    "BREMEN",
    "BREMERHAVEN",
    "BRUNSBUTTEL",
    "CUXHAVEN",
    "EMDEN",
    "HAMBURG",
    "HUSUM",
    "KIEL",
    "ROSTOCK",
    "STRALSUND",
    "WISMAR",
}


def _sea_path(origin: tuple[float, float], destination: tuple[float, float]) -> list | None:
    """Sea-lane geometry as [[lon, lat], ...], or None if no route is found."""
    try:
        import searoute as sr

        route = sr.searoute(origin, destination)
    except Exception:
        return None
    coordinates = (route or {}).get("geometry", {}).get("coordinates")
    if not coordinates or len(coordinates) < 2:
        return None
    return [[round(float(lon), 4), round(float(lat), 4)] for lon, lat in coordinates]


def build() -> pd.DataFrame:
    voyages = pd.read_csv(VOYAGES_PATH)
    for column in ("from_port", "to_port"):
        voyages[column] = voyages[column].astype(str).str.upper().str.strip()

    from_model = voyages["from_port"].isin(MODEL_PORTS)
    to_model = voyages["to_port"].isin(MODEL_PORTS)
    voyages = voyages.loc[from_model | to_model].copy()

    # Attribute each voyage to its German endpoint, so an inbound voyage counts
    # against the port it arrives at rather than a foreign origin the model
    # knows nothing about. Without this, everything arriving in Germany would
    # carry no value and vanish from the map.
    voyages["model_port"] = voyages["from_port"].where(from_model, voyages["to_port"])

    grouped = voyages.groupby(
        ["from_port", "to_port", "model_port"], as_index=False
    ).agg(
        voyages=("imo", "size"),
        vessels=("imo", "nunique"),
        distance_nm=("final_distance_nm", "mean"),
        from_lat=("from_lat", "first"),
        from_lon=("from_lon", "first"),
        to_lat=("to_lat", "first"),
        to_lon=("to_lon", "first"),
    )
    grouped = grouped.dropna(subset=["from_lat", "from_lon", "to_lat", "to_lon"])

    paths = []
    for row in grouped.itertuples(index=False):
        path = _sea_path((row.from_lon, row.from_lat), (row.to_lon, row.to_lat))
        # Fall back to a straight origin/destination segment so a pair searoute
        # cannot solve still appears, rather than silently disappearing.
        if path is None:
            path = [
                [round(float(row.from_lon), 4), round(float(row.from_lat), 4)],
                [round(float(row.to_lon), 4), round(float(row.to_lat), 4)],
            ]
        paths.append(json.dumps(path))
    grouped["path"] = paths
    return grouped


def main() -> None:
    frame = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT_PATH, index=False)
    print(f"wrote {len(frame):,} sea routes -> {OUTPUT_PATH}")
    print(f"  model ports covered: {frame['model_port'].nunique()}")
    print(f"  destinations reached: {frame['to_port'].nunique()}")
    print(f"  voyages represented: {frame['voyages'].sum():,}")


if __name__ == "__main__":
    main()
