from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.airport_metadata import load_airport_metadata
from navaero_transition_model.aviation_preprocessing.common import (
    normalize_icao24,
    normalize_registration,
    snake_case_columns,
    write_parquet_compatible,
)

FLIGHTLIST_COLUMN_ALIASES = {
    "icao24": "icao24",
    "registration": "registration",
    "typecode": "typecode",
    "origin": "origin",
    "originairport": "origin",
    "destination": "destination",
    "destinationairport": "destination",
    "firstseen": "firstseen",
    "lastseen": "lastseen",
    "day": "day",
}

FLIGHTLIST_KEEP_COLUMNS = (
    "icao24",
    "registration",
    "typecode",
    "origin",
    "destination",
    "firstseen",
    "lastseen",
    "day",
)


@dataclass
class FlightlistIngestionConfig:
    input_folder: Path
    output_parquet_path: Path = Path("data/processed/aviation/opensky_flightlist_processed.parquet")
    year_start: int | None = None
    year_end: int | None = None
    airports: set[str] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)
    aircraft_types: set[str] = field(default_factory=set)
    airport_metadata_path: Path | None = None


class OpenSkyFlightlistIngestor:
    def __init__(self, config: FlightlistIngestionConfig) -> None:
        self.config = config

    def _read_one(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(path, compression="infer")
        normalized = snake_case_columns(frame).rename(columns=FLIGHTLIST_COLUMN_ALIASES)
        available_columns = [
            column for column in FLIGHTLIST_KEEP_COLUMNS if column in normalized.columns
        ]
        if not available_columns:
            raise ValueError(f"Flightlist file has no usable columns: {path}")
        subset = normalized.loc[:, available_columns].copy()
        for column in subset.select_dtypes(include=["object", "string"]).columns:
            subset[column] = subset[column].fillna("").astype(str).str.strip()
        if "icao24" in subset.columns:
            subset["icao24"] = subset["icao24"].map(normalize_icao24)
        if "registration" in subset.columns:
            subset["registration"] = subset["registration"].map(normalize_registration)
        if "typecode" in subset.columns:
            subset["typecode"] = subset["typecode"].astype(str).str.upper().str.strip()
        for column in ("origin", "destination"):
            if column in subset.columns:
                subset[column] = subset[column].astype(str).str.upper().str.strip()
        for column in ("firstseen", "lastseen", "day"):
            if column in subset.columns:
                subset[column] = pd.to_datetime(subset[column], errors="coerce", utc=False)
        return subset

    def ingest(self) -> pd.DataFrame:
        input_folder = self.config.input_folder
        if not input_folder.exists():
            raise FileNotFoundError(f"Flightlist input folder not found: {input_folder}")
        files = sorted(
            [
                path
                for path in input_folder.iterdir()
                if path.is_file() and path.suffix.lower() in {".csv", ".gz"}
            ],
        )
        if not files:
            raise ValueError(f"No monthly flightlist CSV/CSV.GZ files found in {input_folder}")

        frames = [self._read_one(path) for path in files]
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.dropna(subset=["origin", "destination"])
        combined = combined.loc[
            (combined["origin"].astype(str).str.strip() != "")
            & (combined["destination"].astype(str).str.strip() != "")
        ].copy()
        combined["year"] = combined["day"].dt.year

        if self.config.year_start is not None:
            combined = combined.loc[combined["year"] >= int(self.config.year_start)]
        if self.config.year_end is not None:
            combined = combined.loc[combined["year"] <= int(self.config.year_end)]
        if self.config.airports:
            airports = {airport.upper().strip() for airport in self.config.airports}
            combined = combined.loc[
                combined["origin"].isin(airports) | combined["destination"].isin(airports)
            ]
        if self.config.aircraft_types:
            aircraft_types = {
                aircraft_type.upper().strip() for aircraft_type in self.config.aircraft_types
            }
            combined = combined.loc[combined["typecode"].isin(aircraft_types)]
        if self.config.countries:
            if self.config.airport_metadata_path is None:
                raise ValueError(
                    "countries filtering requires airport_metadata_path so airport-country lookup "
                    "can be constructed.",
                )
            airports = load_airport_metadata(self.config.airport_metadata_path)
            airport_lookup = airports.set_index("airport_code")["country"].to_dict()
            combined["origin_country"] = combined["origin"].map(airport_lookup).fillna("")
            combined["destination_country"] = combined["destination"].map(airport_lookup).fillna("")
            wanted_countries = {country.strip() for country in self.config.countries}
            combined = combined.loc[
                combined["origin_country"].isin(wanted_countries)
                | combined["destination_country"].isin(wanted_countries)
            ]

        combined = combined.reset_index(drop=True)
        write_parquet_compatible(combined, self.config.output_parquet_path)
        return combined
