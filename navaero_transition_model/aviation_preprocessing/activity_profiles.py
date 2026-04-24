from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.airport_metadata import load_airport_metadata
from navaero_transition_model.aviation_preprocessing.common import (
    ensure_parent_dir,
    great_circle_distance_km,
    read_parquet_compatible,
)


@dataclass
class AviationActivityProfileOutputs:
    by_type: pd.DataFrame
    by_operator_type: pd.DataFrame
    by_airport_type: pd.DataFrame
    by_registration: pd.DataFrame


@dataclass
class AviationActivityProfileBuilder:
    airport_metadata_path: Path
    short_haul_threshold_km: float = 1500.0
    medium_haul_threshold_km: float = 4000.0

    def _prepare(
        self, flightlist_frame: pd.DataFrame, aircraft_db: pd.DataFrame | None
    ) -> pd.DataFrame:
        airports = load_airport_metadata(self.airport_metadata_path)
        airport_lookup = airports.set_index("airport_code")[
            ["country", "region", "bundesland", "nuts3", "latitude_deg", "longitude_deg"]
        ]

        flights = flightlist_frame.copy()
        flights["typecode"] = flights["typecode"].astype(str).str.upper().str.strip()
        flights["origin"] = flights["origin"].astype(str).str.upper().str.strip()
        flights["destination"] = flights["destination"].astype(str).str.upper().str.strip()

        origin_data = airport_lookup.add_prefix("origin_")
        destination_data = airport_lookup.add_prefix("destination_")
        flights = flights.join(origin_data, on="origin")
        flights = flights.join(destination_data, on="destination")
        flights = flights.dropna(
            subset=[
                "origin_latitude_deg",
                "origin_longitude_deg",
                "destination_latitude_deg",
                "destination_longitude_deg",
            ],
        ).copy()
        flights["route_distance_km"] = flights.apply(
            lambda row: great_circle_distance_km(
                float(row["origin_latitude_deg"]),
                float(row["origin_longitude_deg"]),
                float(row["destination_latitude_deg"]),
                float(row["destination_longitude_deg"]),
            ),
            axis=1,
        )
        flights["domestic_flag"] = (
            flights["origin_country"].astype(str).str.strip()
            == flights["destination_country"].astype(str).str.strip()
        )
        flights["international_flag"] = ~flights["domestic_flag"]
        flights["haul_class"] = "medium"
        flights.loc[flights["route_distance_km"] < self.short_haul_threshold_km, "haul_class"] = (
            "short"
        )
        flights.loc[flights["route_distance_km"] > self.medium_haul_threshold_km, "haul_class"] = (
            "long"
        )

        if aircraft_db is not None and not aircraft_db.empty:
            metadata = aircraft_db.copy()
            metadata = metadata.drop_duplicates(subset=["registration", "icao24"], keep="first")
            join_columns = ["registration", "icao24", "operator"]
            flights = flights.merge(
                metadata[join_columns], on=["registration", "icao24"], how="left"
            )
            if "operator" in flights.columns:
                flights = flights.rename(columns={"operator": "operator_name"})
        if "operator_name" not in flights.columns:
            flights["operator_name"] = ""
        return flights.reset_index(drop=True)

    def _annualized_profile(
        self,
        dataframe: pd.DataFrame,
        group_columns: list[str],
    ) -> pd.DataFrame:
        if dataframe.empty:
            return pd.DataFrame(columns=group_columns)

        grouped = dataframe.groupby(group_columns + ["year"], dropna=False).agg(
            departures=("origin", "count"),
            average_route_distance_km=("route_distance_km", "mean"),
            median_route_distance_km=("route_distance_km", "median"),
            domestic_share=("domestic_flag", "mean"),
            international_share=("international_flag", "mean"),
            short_haul_share=("haul_class", lambda values: (pd.Series(values) == "short").mean()),
            medium_haul_share=("haul_class", lambda values: (pd.Series(values) == "medium").mean()),
            long_haul_share=("haul_class", lambda values: (pd.Series(values) == "long").mean()),
            annual_distance_km=("route_distance_km", "sum"),
        )
        annualized = grouped.groupby(level=group_columns).mean(numeric_only=True).reset_index()
        annualized = annualized.rename(columns={"departures": "annual_departures"})
        return annualized

    def build(
        self,
        *,
        processed_flightlist_path: str | Path,
        aircraft_db_processed_path: str | Path | None = None,
        output_dir: str | Path = "data/processed/aviation",
    ) -> AviationActivityProfileOutputs:
        flights = read_parquet_compatible(processed_flightlist_path)
        aircraft_db = None
        if aircraft_db_processed_path is not None and Path(aircraft_db_processed_path).exists():
            aircraft_db = pd.read_csv(aircraft_db_processed_path)
        prepared = self._prepare(flights, aircraft_db)

        by_type = self._annualized_profile(prepared, ["typecode"])
        by_operator_type = self._annualized_profile(
            prepared.loc[prepared["operator_name"].astype(str).str.strip() != ""],
            ["operator_name", "typecode"],
        )
        by_airport_type = self._annualized_profile(prepared, ["origin", "typecode"])

        registration_frame = prepared.loc[
            (prepared["registration"].astype(str).str.strip() != "")
            | (prepared["icao24"].astype(str).str.strip() != "")
        ].copy()
        if registration_frame.empty:
            by_registration = pd.DataFrame(
                columns=[
                    "registration",
                    "icao24",
                    "annual_departures",
                    "annual_distance_km",
                    "annual_flights",
                ],
            )
        else:
            yearly = registration_frame.groupby(
                ["registration", "icao24", "year"], dropna=False
            ).agg(
                annual_departures=("origin", "count"),
                annual_distance_km=("route_distance_km", "sum"),
            )
            by_registration = (
                yearly.groupby(level=["registration", "icao24"])
                .mean(
                    numeric_only=True,
                )
                .reset_index()
            )
            by_registration["annual_flights"] = by_registration["annual_departures"]

        output_path = Path(output_dir)
        ensure_parent_dir(output_path / "aviation_activity_profiles_by_type.csv")
        by_type.to_csv(output_path / "aviation_activity_profiles_by_type.csv", index=False)
        by_operator_type.to_csv(
            output_path / "aviation_activity_profiles_by_operator_type.csv",
            index=False,
        )
        by_airport_type.to_csv(
            output_path / "aviation_activity_profiles_by_airport_type.csv",
            index=False,
        )
        by_registration.to_csv(
            output_path / "aviation_activity_profiles_by_registration.csv",
            index=False,
        )
        return AviationActivityProfileOutputs(
            by_type=by_type,
            by_operator_type=by_operator_type,
            by_airport_type=by_airport_type,
            by_registration=by_registration,
        )
