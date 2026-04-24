from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from navaero_transition_model.aviation_preprocessing.activity_profiles import (
    AviationActivityProfileBuilder,
)
from navaero_transition_model.aviation_preprocessing.common import (
    ensure_parent_dir,
    read_parquet_compatible,
)
from navaero_transition_model.aviation_preprocessing.filters import filter_german_airport_departures


@dataclass
class AviationAllocationOutputs:
    airport_allocation: pd.DataFrame
    regional_allocation: pd.DataFrame


@dataclass
class AviationAllocationBuilder:
    airport_metadata_path: Path

    def build(
        self,
        *,
        processed_flightlist_path: str | Path,
        aircraft_db_processed_path: str | Path | None = None,
        output_dir: str | Path = "data/processed/aviation",
    ) -> AviationAllocationOutputs:
        builder = AviationActivityProfileBuilder(airport_metadata_path=self.airport_metadata_path)
        prepared = builder._prepare(
            read_parquet_compatible(processed_flightlist_path),
            pd.read_csv(aircraft_db_processed_path)
            if aircraft_db_processed_path is not None and Path(aircraft_db_processed_path).exists()
            else None,
        )
        german_departures = filter_german_airport_departures(prepared)
        if german_departures.empty:
            airport_allocation = pd.DataFrame(
                columns=[
                    "origin",
                    "typecode",
                    "annual_departures",
                    "average_route_distance_km",
                    "domestic_share",
                    "international_share",
                    "share_airport_within_type",
                    "share_airport_within_operator_type",
                ],
            )
            regional_allocation = pd.DataFrame(
                columns=[
                    "bundesland",
                    "nuts3",
                    "typecode",
                    "annual_departures",
                    "average_route_distance_km",
                    "domestic_share",
                    "international_share",
                ],
            )
        else:
            airport_year = german_departures.groupby(
                ["origin", "typecode", "year"], dropna=False
            ).agg(
                annual_departures=("origin", "count"),
                average_route_distance_km=("route_distance_km", "mean"),
                domestic_share=("domestic_flag", "mean"),
                international_share=("international_flag", "mean"),
            )
            airport_allocation = (
                airport_year.groupby(level=["origin", "typecode"])
                .mean(
                    numeric_only=True,
                )
                .reset_index()
            )
            airport_allocation["share_airport_within_type"] = airport_allocation.groupby(
                "typecode"
            )["annual_departures"].transform(
                lambda values: values / values.sum() if values.sum() else 0.0
            )

            operator_airport = (
                german_departures.loc[
                    german_departures["operator_name"].astype(str).str.strip() != ""
                ]
                .groupby(["origin", "operator_name", "typecode", "year"], dropna=False)
                .agg(
                    annual_departures=("origin", "count"),
                )
            )
            operator_airport = (
                operator_airport.groupby(level=["origin", "operator_name", "typecode"])
                .mean(
                    numeric_only=True,
                )
                .reset_index()
            )
            operator_airport["share_airport_within_operator_type"] = operator_airport.groupby(
                ["operator_name", "typecode"],
            )["annual_departures"].transform(
                lambda values: values / values.sum() if values.sum() else 0.0,
            )
            airport_allocation = airport_allocation.merge(
                operator_airport[
                    ["origin", "operator_name", "typecode", "share_airport_within_operator_type"]
                ],
                on=["origin", "typecode"],
                how="left",
            )

            regional_year = german_departures.groupby(
                ["origin_bundesland", "origin_nuts3", "typecode", "year"],
                dropna=False,
            ).agg(
                annual_departures=("origin", "count"),
                average_route_distance_km=("route_distance_km", "mean"),
                domestic_share=("domestic_flag", "mean"),
                international_share=("international_flag", "mean"),
            )
            regional_allocation = (
                regional_year.groupby(
                    level=["origin_bundesland", "origin_nuts3", "typecode"],
                )
                .mean(numeric_only=True)
                .reset_index()
                .rename(
                    columns={"origin_bundesland": "bundesland", "origin_nuts3": "nuts3"},
                )
            )

        output_path = Path(output_dir)
        ensure_parent_dir(output_path / "aviation_airport_allocation.csv")
        airport_allocation.to_csv(output_path / "aviation_airport_allocation.csv", index=False)
        regional_allocation.to_csv(output_path / "aviation_regional_allocation.csv", index=False)
        return AviationAllocationOutputs(
            airport_allocation=airport_allocation,
            regional_allocation=regional_allocation,
        )
