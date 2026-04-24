from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import (
    ensure_parent_dir,
    infer_is_german_flag,
    normalize_icao24,
    normalize_operator_name,
    normalize_registration,
    registration_prefix,
    safe_numeric_series,
    snake_case_columns,
)

DEFAULT_OPENSKY_AIRCRAFT_DB_URL = (
    "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
)

OPENSKY_COLUMN_ALIASES = {
    "icao24": "icao24",
    "registration": "registration",
    "manufacturername": "manufacturer_name",
    "manufacturer_name": "manufacturer_name",
    "model": "model",
    "typecode": "typecode",
    "operator": "operator",
    "owner": "owner",
    "country": "country",
    "status": "status",
    "built": "built",
    "built_year": "built",
    "serialnumber": "serial_number",
    "serial_number": "serial_number",
    "registeredowner": "owner",
}

OPENSKY_KEEP_COLUMNS = (
    "icao24",
    "registration",
    "manufacturer_name",
    "model",
    "typecode",
    "operator",
    "owner",
    "country",
    "status",
    "built",
    "serial_number",
)


@dataclass
class OpenSkyAircraftDatabaseConfig:
    source_url: str = DEFAULT_OPENSKY_AIRCRAFT_DB_URL
    raw_snapshot_dir: Path = Path("data/raw/aviation/opensky_aircraft_db")
    processed_output_path: Path = Path("data/processed/aviation/opensky_aircraft_db_processed.csv")
    timeout_seconds: int = 120
    user_agent: str = "NATM-aviation-preprocessing/1.0"


class OpenSkyAircraftDatabaseProcessor:
    def __init__(self, config: OpenSkyAircraftDatabaseConfig | None = None) -> None:
        self.config = config or OpenSkyAircraftDatabaseConfig()

    def download_snapshot(
        self,
        *,
        snapshot_name: str = "latest",
        source_url: str | None = None,
    ) -> Path:
        url = source_url or self.config.source_url
        target = ensure_parent_dir(self.config.raw_snapshot_dir / f"{snapshot_name}.csv")
        request = Request(url, headers={"User-Agent": self.config.user_agent})
        with (
            urlopen(request, timeout=self.config.timeout_seconds) as response,
            target.open(
                "wb",
            ) as handle,
        ):
            handle.write(response.read())
        return target

    def process(
        self, raw_csv_path: str | Path, output_path: str | Path | None = None
    ) -> pd.DataFrame:
        dataframe = pd.read_csv(raw_csv_path)
        if dataframe.empty:
            raise ValueError(f"OpenSky aircraft database CSV has no rows: {raw_csv_path}")

        normalized = snake_case_columns(dataframe).rename(columns=OPENSKY_COLUMN_ALIASES)
        for column in OPENSKY_KEEP_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA

        extra_columns = [
            column
            for column in ("engine_manufacturer", "engine_type", "engine_count", "seat_total")
            if column in normalized.columns
        ]
        keep_columns = list(OPENSKY_KEEP_COLUMNS) + extra_columns
        processed = normalized.loc[:, keep_columns].copy()

        object_columns = processed.select_dtypes(include=["object", "string"]).columns
        for column in object_columns:
            processed[column] = processed[column].fillna("").astype(str).str.strip()

        processed["registration"] = processed["registration"].map(normalize_registration)
        processed["icao24"] = processed["icao24"].map(normalize_icao24)
        processed["operator"] = processed["operator"].astype(str).str.strip()
        processed["owner"] = processed["owner"].astype(str).str.strip()
        processed["country"] = processed["country"].astype(str).str.strip()
        processed["built"] = processed["built"].astype(str).str.strip()
        processed["serial_number"] = processed["serial_number"].astype(str).str.strip()
        if "engine_manufacturer" in processed.columns:
            processed["engine_manufacturer"] = processed["engine_manufacturer"].map(
                normalize_operator_name,
            )
        if "engine_type" in processed.columns:
            processed["engine_type"] = processed["engine_type"].astype(str).str.strip()
        if "engine_count" in processed.columns:
            processed["engine_count"] = safe_numeric_series(processed["engine_count"]).astype(
                "Int64"
            )
        if "seat_total" in processed.columns:
            processed["seat_total"] = safe_numeric_series(processed["seat_total"])

        processed["registration_prefix"] = processed["registration"].map(registration_prefix)
        processed["built_year"] = safe_numeric_series(processed["built"]).astype("Int64")
        processed["is_german_flag"] = processed["registration"].map(infer_is_german_flag)
        processed["operator_normalized"] = processed["operator"].map(normalize_operator_name)
        processed["owner_normalized"] = processed["owner"].map(normalize_operator_name)
        processed["model_normalized"] = (
            processed["model"].astype(str).str.lower().str.replace(" ", "", regex=False)
        )
        processed["typecode_normalized"] = (
            processed["typecode"].astype(str).str.lower().str.replace(" ", "", regex=False)
        )

        destination = output_path or self.config.processed_output_path
        ensure_parent_dir(destination)
        processed.to_csv(destination, index=False)
        return processed.reset_index(drop=True)

    def download_and_process(
        self,
        *,
        snapshot_name: str = "latest",
        source_url: str | None = None,
        output_path: str | Path | None = None,
    ) -> pd.DataFrame:
        raw_path = self.download_snapshot(snapshot_name=snapshot_name, source_url=source_url)
        return self.process(raw_path, output_path=output_path)
