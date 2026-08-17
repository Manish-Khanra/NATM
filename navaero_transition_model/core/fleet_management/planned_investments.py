from __future__ import annotations

import re

import pandas as pd

PLANNED_INVESTMENT_COLUMNS = (
    "aircraft_id",
    "investment_year",
    "technology_name",
    "technology_pattern",
)

_PLANNED_INVESTMENT_YEAR_PATTERN = re.compile(r"planned_investment_(\d+)_year")


def _optional_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return text


def planned_investments_from_fleet(fleet_frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize numbered planned-investment columns from a fleet-stock frame.

    Recognizes ``planned_investment_<n>_year``, ``planned_investment_<n>_technology_name``,
    and ``planned_investment_<n>_technology_pattern`` columns (n = 1, 2, 3, ...) and
    returns one row per scheduled event.
    """
    event_numbers = sorted(
        {
            int(match.group(1))
            for column in fleet_frame.columns
            if (match := _PLANNED_INVESTMENT_YEAR_PATTERN.fullmatch(str(column)))
        },
    )
    if not event_numbers:
        return pd.DataFrame(columns=PLANNED_INVESTMENT_COLUMNS)

    rows: list[dict[str, object]] = []
    for aircraft in fleet_frame.to_dict(orient="records"):
        for event_number in event_numbers:
            prefix = f"planned_investment_{event_number}_"
            year = aircraft.get(f"{prefix}year")
            if pd.isna(year):
                continue
            technology_name = _optional_text(aircraft.get(f"{prefix}technology_name"))
            technology_pattern = _optional_text(aircraft.get(f"{prefix}technology_pattern"))
            if not technology_name and not technology_pattern:
                raise ValueError(
                    f"Aircraft {aircraft.get('aircraft_id')} planned investment "
                    f"{event_number} requires a technology_name or technology_pattern",
                )
            rows.append(
                {
                    "aircraft_id": int(aircraft["aircraft_id"]),
                    "investment_year": int(float(year)),
                    "technology_name": technology_name,
                    "technology_pattern": technology_pattern,
                },
            )
    return pd.DataFrame(rows, columns=PLANNED_INVESTMENT_COLUMNS)
