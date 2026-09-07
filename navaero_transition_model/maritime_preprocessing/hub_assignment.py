from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Anonymized/unidentified GFW port codes (e.g. "DEU-482") carry no usable
# place name -- treat them the same as a missing port_name rather than
# presenting a code as a vessel's home port.
_ANONYMIZED_PORT_CODE = re.compile(r"^[A-Z]{3}-\d+$")

# The columns `apply_hub_assignment` itself writes, plus the `_x`/`_y` names
# pandas produces when a merge collides with them. Dropped before the merge so
# the function is idempotent -- see `_drop_derived_columns`.
_DERIVED_COLUMNS = frozenset(
    f"{base}{suffix}"
    for base in ("Main Hub", "main_hub", "main_hub_match_method")
    for suffix in ("", "_x", "_y")
)


def _drop_derived_columns(fleet: pd.DataFrame) -> pd.DataFrame:
    """Removes any output columns left over from a previous run.

    Without this, re-running `apply_hub_assignment` on an already-processed
    fleet-stock file merges `main_hub_match_method` into a frame that already
    has one: pandas splits them into `main_hub_match_method_x`/`_y`, the file
    is written back silently corrupted, and the run after that fails outright
    with a `MergeError`. Dropping the suffixed variants too means a file
    already damaged that way is repaired rather than accumulating columns.
    """
    return fleet.drop(columns=[column for column in fleet.columns if column in _DERIVED_COLUMNS])


def derive_vessel_hubs(port_visits: pd.DataFrame, fleet_imos: set[int]) -> pd.DataFrame:
    """Derives each vessel's real home port from AIS port-visit history.

    For every IMO in `fleet_imos`, sums `duration_hours` per German port
    visited and picks the port with the most total time -- a vessel passing
    through a port briefly many times should not outrank one port where it
    actually lays up for long stretches. Vessels with no recorded German
    port visit (no AIS coverage, or none of their recorded ports has a real
    name) are simply absent from the result; callers decide the fallback.

    Returns columns: imo, main_hub, main_hub_match_method.
    """
    german = port_visits.loc[
        port_visits["is_germany"].astype(bool) & port_visits["imo"].isin(fleet_imos)
    ].copy()
    german["port_name"] = german["port_name"].astype("string")
    known_port = german["port_name"].notna() & ~german["port_name"].str.match(
        _ANONYMIZED_PORT_CODE, na=False,
    )
    german = german.loc[known_port]
    german["duration_hours"] = pd.to_numeric(german["duration_hours"], errors="coerce").fillna(0.0)

    if german.empty:
        return pd.DataFrame(columns=["imo", "main_hub", "main_hub_match_method"])

    totals = german.groupby(["imo", "port_name"], as_index=False)["duration_hours"].sum()
    top_index = totals.groupby("imo")["duration_hours"].idxmax()
    top = totals.loc[top_index, ["imo", "port_name"]].reset_index(drop=True)
    top["main_hub"] = top.pop("port_name").str.title()
    top["main_hub_match_method"] = "ais_port_visits_2024_duration_weighted"
    return top


def apply_hub_assignment(
    fleet_stock_path: str | Path,
    port_visits_path: str | Path,
    *,
    fallback_hub: str = "Hamburg",
) -> pd.DataFrame:
    """Updates `Main Hub` in a maritime fleet-stock CSV using real AIS-derived
    home ports, in place. Vessels with no recorded German port visit keep
    `fallback_hub`, tagged as `fallback_default_<hub>` in the new
    `main_hub_match_method` column so it's clear which rows are a real,
    per-vessel match versus a fleet-wide default.

    Returns the updated DataFrame (also written back to `fleet_stock_path`).
    """
    fleet_stock_path = Path(fleet_stock_path)
    fleet = pd.read_csv(fleet_stock_path, low_memory=False)
    port_visits = pd.read_csv(port_visits_path, low_memory=False)

    fleet_imos = set(fleet["imo"].dropna().astype(int))
    hubs = derive_vessel_hubs(port_visits, fleet_imos)

    fleet = _drop_derived_columns(fleet).merge(hubs, on="imo", how="left")
    unmatched = fleet["main_hub"].isna()
    fleet.loc[unmatched, "main_hub_match_method"] = f"fallback_default_{fallback_hub.lower()}"
    fleet.loc[unmatched, "main_hub"] = fallback_hub
    fleet = fleet.rename(columns={"main_hub": "Main Hub"})

    fleet.to_csv(fleet_stock_path, index=False)
    return fleet
