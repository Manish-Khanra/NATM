from __future__ import annotations

import math
import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd


def ensure_parent_dir(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def read_parquet_compatible(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    try:
        return pd.read_parquet(target)
    except (ImportError, ValueError, OSError):
        return pd.read_pickle(target)


def write_parquet_compatible(dataframe: pd.DataFrame, path: str | Path) -> Path:
    target = ensure_parent_dir(path)
    try:
        dataframe.to_parquet(target, index=False)
    except (ImportError, ValueError, OSError):
        dataframe.to_pickle(target)
    return target


def snake_case(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "_", str(value).strip())
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_").lower()


def snake_case_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    renamed = dataframe.copy()
    renamed.columns = [snake_case(column) for column in renamed.columns]
    return renamed


def normalize_text(value: object, *, uppercase: bool = False, lowercase: bool = False) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if uppercase:
        return text.upper()
    if lowercase:
        return text.lower()
    return text


def normalize_registration(value: object) -> str:
    return normalize_text(value, uppercase=True).replace(" ", "")


def normalize_icao24(value: object) -> str:
    return normalize_text(value, lowercase=True).replace(" ", "")


def normalize_operator_name(value: object) -> str:
    return re.sub(r"\s+", " ", normalize_text(value, uppercase=True))


def normalize_descriptor(value: object) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", normalize_text(value, lowercase=True))
    return cleaned


def safe_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def safe_datetime_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=False)


def registration_prefix(value: object) -> str:
    registration = normalize_registration(value)
    if not registration:
        return ""
    prefix = registration.split("-", maxsplit=1)[0]
    return prefix


def infer_is_german_flag(registration: object) -> bool:
    return normalize_registration(registration).startswith("D-")


def year_columns(dataframe: pd.DataFrame) -> list[str]:
    return sorted([column for column in dataframe.columns if str(column).isdigit()], key=int)


def choose_first_non_empty(values: Iterable[object]) -> object:
    for value in values:
        if pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return pd.NA


def great_circle_distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius_km = 6371.0088
    lat_1 = math.radians(latitude_a)
    lon_1 = math.radians(longitude_a)
    lat_2 = math.radians(latitude_b)
    lon_2 = math.radians(longitude_b)
    delta_lat = lat_2 - lat_1
    delta_lon = lon_2 - lon_1

    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lon / 2) ** 2
    )
    central_angle = 2 * math.asin(math.sqrt(max(haversine, 0.0)))
    return radius_km * central_angle
