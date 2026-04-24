from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import snake_case_columns

AIRPORT_COLUMN_ALIASES = {
    "iata": "iata_code",
    "iata_code": "iata_code",
    "iata_airport_code": "iata_code",
    "icao": "icao_code",
    "icao_code": "icao_code",
    "name": "airport_name",
    "airport_name": "airport_name",
    "city": "city",
    "country": "country",
    "country_name": "country",
    "region": "region",
    "state": "region",
    "bundesland": "bundesland",
    "nuts3": "nuts3",
    "latitude": "latitude_deg",
    "latitude_deg": "latitude_deg",
    "longitude": "longitude_deg",
    "longitude_deg": "longitude_deg",
}


def load_airport_metadata(path: str | Path) -> pd.DataFrame:
    return AirportMetadataLoader().load(path)


@dataclass
class AirportMetadataLoader:
    def load(self, path: str | Path) -> pd.DataFrame:
        csv_path = Path(path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Airport metadata file not found: {csv_path}")
        dataframe = pd.read_csv(csv_path)
        if dataframe.empty:
            raise ValueError(f"Airport metadata file has no rows: {csv_path}")

        normalized = snake_case_columns(dataframe).rename(columns=AIRPORT_COLUMN_ALIASES)
        required = ("latitude_deg", "longitude_deg")
        missing = [column for column in required if column not in normalized.columns]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Airport metadata is missing required columns: {missing_text}")

        for column in normalized.select_dtypes(include=["object", "string"]).columns:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        normalized["latitude_deg"] = pd.to_numeric(normalized["latitude_deg"], errors="coerce")
        normalized["longitude_deg"] = pd.to_numeric(normalized["longitude_deg"], errors="coerce")

        if "iata_code" not in normalized.columns:
            normalized["iata_code"] = ""
        if "icao_code" not in normalized.columns:
            normalized["icao_code"] = ""
        normalized["iata_code"] = normalized["iata_code"].astype(str).str.upper().str.strip()
        normalized["icao_code"] = normalized["icao_code"].astype(str).str.upper().str.strip()
        normalized["airport_code"] = normalized["iata_code"]
        blank_iata = normalized["airport_code"].eq("")
        normalized.loc[blank_iata, "airport_code"] = normalized.loc[blank_iata, "icao_code"]
        return normalized.reset_index(drop=True)
