from __future__ import annotations

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import infer_is_german_flag


def filter_german_flag_fleet(fleet_frame: pd.DataFrame) -> pd.DataFrame:
    filtered = fleet_frame.copy()
    if "is_german_flag" in filtered.columns:
        mask = filtered["is_german_flag"].fillna(False).astype(bool)
    else:
        mask = filtered.get("registration", pd.Series(index=filtered.index, dtype=object)).map(
            infer_is_german_flag,
        )
    return filtered.loc[mask].reset_index(drop=True)


def filter_german_airport_departures(
    departures_frame: pd.DataFrame,
    *,
    airport_column: str = "origin",
    country_column: str = "origin_country",
) -> pd.DataFrame:
    filtered = departures_frame.copy()
    if country_column in filtered.columns:
        mask = filtered[country_column].astype(str).str.strip().eq("Germany")
        return filtered.loc[mask].reset_index(drop=True)

    if airport_column not in filtered.columns:
        raise ValueError(
            f"departures frame must contain '{country_column}' or '{airport_column}' to filter "
            "German airport departures.",
        )
    german_airport_codes = {
        "BER",
        "BRE",
        "CGN",
        "DRS",
        "DTM",
        "DUS",
        "FMO",
        "FRA",
        "HAJ",
        "HAM",
        "LEJ",
        "MUC",
        "NUE",
        "PAD",
        "SCN",
        "STR",
    }
    mask = filtered[airport_column].astype(str).str.strip().str.upper().isin(german_airport_codes)
    return filtered.loc[mask].reset_index(drop=True)
