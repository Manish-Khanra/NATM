from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from navaero_transition_model.postprocessing.hourly_timeseries import (
    HOURS_PER_WEEK,
    _hour_weights_for_year,
    expand_to_hourly,
    maritime_weekly_activity_shape,
)


def _write_aircraft_csv(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "aircraft_id": 1,
                "operator_name": "TestAir",
                "year": 2025,
                "main_hub_base": "EDDF",
                "primary_energy_carrier": "kerosene",
                "primary_energy_consumption": 8760.0,
                "secondary_energy_carrier": "saf",
                "secondary_energy_consumption": 100.0,
            },
            {
                "aircraft_id": 2,
                "operator_name": "TestAir",
                "year": 2025,
                "main_hub_base": "EDDM",
                "primary_energy_carrier": "hydrogen",
                "primary_energy_consumption": 4380.0,
                "secondary_energy_carrier": "none",
                "secondary_energy_consumption": 0.0,
            },
            # 2028 is a leap year -- exercises the 8784-hour path.
            {
                "aircraft_id": 1,
                "operator_name": "TestAir",
                "year": 2028,
                "main_hub_base": "EDDF",
                "primary_energy_carrier": "kerosene",
                "primary_energy_consumption": 8784.0,
                "secondary_energy_carrier": "none",
                "secondary_energy_consumption": 0.0,
            },
        ],
    ).to_csv(path, index=False)


def test_hour_weights_sum_to_one_for_normal_and_leap_years() -> None:
    uniform_shape = np.full(HOURS_PER_WEEK, 1.0 / HOURS_PER_WEEK)

    hours_2025, weights_2025 = _hour_weights_for_year(2025, uniform_shape)
    assert len(hours_2025) == 8760
    assert weights_2025.sum() == pytest.approx(1.0)

    hours_2028, weights_2028 = _hour_weights_for_year(2028, uniform_shape)
    assert len(hours_2028) == 8784
    assert weights_2028.sum() == pytest.approx(1.0)


def test_expand_to_hourly_reconstructs_annual_totals_exactly(tmp_path: Path) -> None:
    aircraft_csv = tmp_path / "aircraft.csv"
    _write_aircraft_csv(aircraft_csv)
    output_path = tmp_path / "hourly.parquet"

    # A non-uniform but simple shape: every hour-of-week gets a distinct
    # weight, still summing to 1 -- exercises real weighting, not just an
    # even split, while keeping the expected reconstruction easy to verify.
    shape = np.arange(1, HOURS_PER_WEEK + 1, dtype=np.float64)
    shape = shape / shape.sum()

    row_count = expand_to_hourly(aircraft_csv, shape, output_path)

    hourly = pd.read_parquet(output_path)
    assert len(hourly) == row_count

    # 2025: aircraft 1 has 2 energy types (primary + secondary), aircraft 2
    # has 1 (secondary is "none" and excluded). 2028: aircraft 1 has 1.
    assert row_count == 8760 * 2 + 8760 * 1 + 8784 * 1

    reconstructed = hourly.groupby(["aircraft_id", "year", "energy_type"])["energy_kwh"].sum()
    assert reconstructed[(1, 2025, "kerosene")] == pytest.approx(8760.0)
    assert reconstructed[(1, 2025, "saf")] == pytest.approx(100.0)
    assert reconstructed[(2, 2025, "hydrogen")] == pytest.approx(4380.0)
    assert reconstructed[(1, 2028, "kerosene")] == pytest.approx(8784.0)

    regions = hourly.drop_duplicates(["aircraft_id"])[["aircraft_id", "region"]]
    assert dict(zip(regions["aircraft_id"], regions["region"], strict=True)) == {
        1: "EDDF",
        2: "EDDM",
    }

    schema = pq.ParquetFile(output_path).schema_arrow
    assert set(schema.names) == {
        "timestamp",
        "aircraft_id",
        "operator_name",
        "year",
        "region",
        "energy_type",
        "energy_kwh",
    }


def test_expand_to_hourly_requires_a_hub_column(tmp_path: Path) -> None:
    aircraft_csv = tmp_path / "aircraft.csv"
    pd.DataFrame([{"aircraft_id": 1, "year": 2025}]).to_csv(aircraft_csv, index=False)

    with pytest.raises(ValueError, match="main_hub_base.*main_hub"):
        expand_to_hourly(
            aircraft_csv,
            np.full(HOURS_PER_WEEK, 1.0 / HOURS_PER_WEEK),
            tmp_path / "hourly.parquet",
        )


def test_expand_to_hourly_requires_known_columns(tmp_path: Path) -> None:
    aircraft_csv = tmp_path / "aircraft.csv"
    pd.DataFrame([{"aircraft_id": 1, "year": 2025, "main_hub_base": "EDDF"}]).to_csv(
        aircraft_csv, index=False,
    )

    with pytest.raises(ValueError, match="missing required columns"):
        expand_to_hourly(
            aircraft_csv,
            np.full(HOURS_PER_WEEK, 1.0 / HOURS_PER_WEEK),
            tmp_path / "hourly.parquet",
        )


def test_maritime_weekly_activity_shape_normalizes_real_timestamps(tmp_path: Path) -> None:
    port_visits = tmp_path / "port_visits.csv"
    # Two visits in the same hour-of-week slot, one in a different slot --
    # the shape should reflect that 2:1 real ratio once normalized.
    pd.DataFrame(
        {
            "start": [
                "2024-01-01 08:00:00+00:00",  # Monday 08:00
                "2024-01-08 08:30:00+00:00",  # Monday 08:00 (same slot)
                "2024-01-02 14:00:00+00:00",  # Tuesday 14:00
            ],
        },
    ).to_csv(port_visits, index=False)

    shape = maritime_weekly_activity_shape(port_visits)

    assert shape.sum() == pytest.approx(1.0)
    monday_08_slot = 0 * 24 + 8
    tuesday_14_slot = 1 * 24 + 14
    assert shape[monday_08_slot] == pytest.approx(2.0 / 3.0)
    assert shape[tuesday_14_slot] == pytest.approx(1.0 / 3.0)
