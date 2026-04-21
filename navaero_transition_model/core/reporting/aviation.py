from __future__ import annotations

from pathlib import Path

import pandas as pd


class AircraftStockExporter:
    def export(self, model) -> pd.DataFrame:
        history_frames = getattr(model, "_aircraft_history_frames", [])
        if not history_frames:
            return pd.DataFrame()
        return pd.concat(history_frames, ignore_index=True)


class AviationTechnologyExporter:
    def export(self, model) -> pd.DataFrame:
        aircraft_frame = AircraftStockExporter().export(model)
        if aircraft_frame.empty:
            return pd.DataFrame()

        aviation_frame = aircraft_frame.loc[aircraft_frame["sector_name"] == "aviation"].copy()
        if aviation_frame.empty:
            return pd.DataFrame()

        grouped = aviation_frame.groupby(
            [
                "year",
                "operator_name",
                "operator_country",
                "segment",
                "current_technology",
                "primary_energy_carrier",
                "secondary_energy_carrier",
                "saf_pathway",
            ],
            dropna=False,
            as_index=False,
        ).agg(
            aircraft_count=("aircraft_id", "count"),
            primary_energy_consumption=("primary_energy_consumption", "sum"),
            secondary_energy_consumption=("secondary_energy_consumption", "sum"),
            total_emission=("total_emission", "sum"),
            chargeable_emission=("chargeable_emission", "sum"),
        )
        return grouped.sort_values(
            ["year", "operator_name", "segment", "current_technology"],
        ).reset_index(drop=True)


class AviationEnergyEmissionsExporter:
    def export(self, model) -> pd.DataFrame:
        technology_frame = AviationTechnologyExporter().export(model)
        if technology_frame.empty:
            return pd.DataFrame()

        grouped = technology_frame.groupby(
            [
                "year",
                "operator_name",
                "operator_country",
                "segment",
                "current_technology",
                "primary_energy_carrier",
                "secondary_energy_carrier",
                "saf_pathway",
            ],
            dropna=False,
            as_index=False,
        ).agg(
            primary_energy_consumption=("primary_energy_consumption", "sum"),
            secondary_energy_consumption=("secondary_energy_consumption", "sum"),
            total_emission=("total_emission", "sum"),
            chargeable_emission=("chargeable_emission", "sum"),
            aircraft_count=("aircraft_count", "sum"),
        )
        return grouped.sort_values(
            [
                "year",
                "operator_name",
                "segment",
                "current_technology",
                "primary_energy_carrier",
                "secondary_energy_carrier",
            ],
        ).reset_index(drop=True)


class AviationInvestmentExporter:
    def export(self, model) -> pd.DataFrame:
        aircraft_frame = AircraftStockExporter().export(model)
        if aircraft_frame.empty:
            return pd.DataFrame()

        investment_year = pd.to_numeric(
            aircraft_frame["investment_year"],
            errors="coerce",
        )
        same_year_investment = investment_year.eq(aircraft_frame["year"])
        investment_frame = aircraft_frame.loc[
            (aircraft_frame["sector_name"] == "aviation")
            & investment_year.notna()
            & same_year_investment
            & (aircraft_frame["investment_cost_eur"] > 0.0),
        ].copy()
        if investment_frame.empty:
            return pd.DataFrame()

        grouped = investment_frame.groupby(
            [
                "year",
                "operator_name",
                "operator_country",
                "segment",
                "current_technology",
            ],
            dropna=False,
            as_index=False,
        ).agg(
            aircraft_count=("aircraft_id", "count"),
            investment_cost_eur=("investment_cost_eur", "sum"),
        )
        return grouped.sort_values(
            ["year", "operator_name", "segment", "current_technology"],
        ).reset_index(drop=True)


class DetailedOutputWriter:
    def export(self, model, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        detail_frames = {
            "agents.csv": model.to_agent_frame(),
            "aircraft.csv": AircraftStockExporter().export(model),
            "aviation_technology.csv": AviationTechnologyExporter().export(model),
            "aviation_energy_emissions.csv": AviationEnergyEmissionsExporter().export(model),
            "aviation_investments.csv": AviationInvestmentExporter().export(model),
        }
        for filename, dataframe in detail_frames.items():
            if dataframe.empty:
                continue
            dataframe.to_csv(output_dir / filename, index=False)
