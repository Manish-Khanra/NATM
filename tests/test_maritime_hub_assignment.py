from __future__ import annotations

from pathlib import Path

import pandas as pd
from navaero_transition_model.maritime_preprocessing import (
    apply_hub_assignment,
    derive_vessel_hubs,
)


def _port_visits() -> pd.DataFrame:
    """Synthetic AIS port-visit history.

    Vessel 1 makes many brief calls at Kiel but lies up in Hamburg for far
    longer overall; vessel 2 only ever visits ports with no usable name; and a
    non-German visit is included to confirm it is filtered out.
    """
    return pd.DataFrame(
        [
            {"imo": 1, "port_name": "KIEL", "duration_hours": 2.0, "is_germany": True},
            {"imo": 1, "port_name": "KIEL", "duration_hours": 2.0, "is_germany": True},
            {"imo": 1, "port_name": "KIEL", "duration_hours": 2.0, "is_germany": True},
            {"imo": 1, "port_name": "HAMBURG", "duration_hours": 40.0, "is_germany": True},
            {"imo": 2, "port_name": "DEU-482", "duration_hours": 99.0, "is_germany": True},
            {"imo": 2, "port_name": None, "duration_hours": 99.0, "is_germany": True},
            {"imo": 3, "port_name": "ROTTERDAM", "duration_hours": 99.0, "is_germany": False},
        ],
    )


def test_derive_vessel_hubs_weights_by_duration_not_visit_count() -> None:
    hubs = derive_vessel_hubs(_port_visits(), {1})

    assert list(hubs["imo"]) == [1]
    # Kiel wins on raw event count (3 visits vs 1) but Hamburg holds the vessel
    # far longer, which is what makes it the home port.
    assert list(hubs["main_hub"]) == ["Hamburg"]
    assert list(hubs["main_hub_match_method"]) == ["ais_port_visits_2024_duration_weighted"]


def test_derive_vessel_hubs_skips_unnamed_and_foreign_ports() -> None:
    hubs = derive_vessel_hubs(_port_visits(), {2, 3})

    # Vessel 2 has only anonymized/null port names, vessel 3 only a non-German
    # call: neither yields a home port, so callers apply their own fallback.
    assert hubs.empty


def _fleet_stock(tmp_path: Path) -> Path:
    path = tmp_path / "maritime_fleet_stock.csv"
    pd.DataFrame(
        [
            {"imo": 1, "vessel_type": "container", "Main Hub": "Hamburg"},
            {"imo": 2, "vessel_type": "bulk", "Main Hub": "Hamburg"},
        ],
    ).to_csv(path, index=False)
    return path


def test_apply_hub_assignment_tags_real_matches_and_fallbacks(tmp_path: Path) -> None:
    fleet_path = _fleet_stock(tmp_path)
    visits_path = tmp_path / "visits.csv"
    _port_visits().to_csv(visits_path, index=False)

    apply_hub_assignment(fleet_path, visits_path, fallback_hub="Hamburg")
    result = pd.read_csv(fleet_path).set_index("imo")

    assert result.loc[1, "Main Hub"] == "Hamburg"
    assert result.loc[1, "main_hub_match_method"] == "ais_port_visits_2024_duration_weighted"
    # Vessel 2 has no derivable port, so it keeps the fleet-wide default -- and
    # must be tagged as such, so a real match is never confused with a guess.
    assert result.loc[2, "Main Hub"] == "Hamburg"
    assert result.loc[2, "main_hub_match_method"] == "fallback_default_hamburg"


def test_apply_hub_assignment_is_idempotent(tmp_path: Path) -> None:
    """Regression test: re-running the CLI must not duplicate its own output
    columns into `_x`/`_y` pairs (which silently corrupted the CSV) nor fail."""
    fleet_path = _fleet_stock(tmp_path)
    visits_path = tmp_path / "visits.csv"
    _port_visits().to_csv(visits_path, index=False)

    apply_hub_assignment(fleet_path, visits_path)
    first = pd.read_csv(fleet_path)
    apply_hub_assignment(fleet_path, visits_path)
    apply_hub_assignment(fleet_path, visits_path)
    third = pd.read_csv(fleet_path)

    assert list(first.columns) == list(third.columns)
    assert not [column for column in third.columns if column.endswith(("_x", "_y"))]
    assert first.equals(third)


def test_apply_hub_assignment_repairs_a_previously_corrupted_file(tmp_path: Path) -> None:
    fleet_path = _fleet_stock(tmp_path)
    visits_path = tmp_path / "visits.csv"
    _port_visits().to_csv(visits_path, index=False)

    apply_hub_assignment(fleet_path, visits_path)
    clean = pd.read_csv(fleet_path)

    corrupted = clean.copy()
    corrupted["main_hub_match_method_x"] = "stale"
    corrupted["main_hub_match_method_y"] = "stale"
    corrupted.to_csv(fleet_path, index=False)

    apply_hub_assignment(fleet_path, visits_path)
    assert pd.read_csv(fleet_path).equals(clean)
