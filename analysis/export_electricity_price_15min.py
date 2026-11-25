"""Joins the 15-minute electricity DEMAND already exported by
export_electricity_15min.py with the REAL 15-minute day-ahead price
(DA_price_EUR_per_MWh) archived in data/archive/price_signal/{scenario}_{year}.csv.
Only the day-ahead price is used -- no aFRR energy/capacity allocation.

Provenance / how the two are linked:
- Each case's scenario.yaml has an `ambiguity_aware_decision.realized_scenario_id`
  -- the one belief-scenario world that case's own simulation actually steps
  through (all 6 risk-neutral cases realize their own scenario; BOTH
  risk-averse cases realize "aktuellepolitiken").
- price_signal has real 15-minute data for 4 milestone years per scenario
  (2030, 2035, 2040, 2045). These are extended to 2025-2050 with the same
  step function the model's own annual scenario CSVs use (2025-2034 -> 2030,
  2035-2039 -> 2035, 2040-2044 -> 2040, 2045-2050 -> 2045). A transplanted
  year keeps the source year's (month, day, hour, minute) values; slots the
  source lacks (Dec 31, Feb 29) are forward-filled.

Output, per sector, wide by (hub, fuel-type) -- the same granularity as
export_electricity_15min.py's own demand file, NOT collapsed to one total
per hub, so a given implied cost can still be traced to the specific
electricity-derived fuel it came from. Prices are one national DE series per
case (not port/airport-specific), so they are not hub- or fuel-differentiated:
  scenario, timestamp, realized_scenario_id,
  day_ahead_price_eur_per_mwh, day_ahead_price_eur_per_kwh,
  "<hub> -- <fuel-type> -- demand_kwh" (one per hub/fuel-type combination),
  "<hub> -- <fuel-type> -- day_ahead_cost_eur" (= demand_kwh x DA price/kWh)

Run:  python analysis/export_electricity_price_15min.py
Out:  data/processed/electricity_15min/{cargo,passenger,maritime_cargo}_electricity_price_15min.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.cartographic_dashboard import ROOT, scenario_sibling_folders  # noqa: E402

PRICE_SIGNAL_DIR = ROOT / "data" / "archive" / "price_signal"
DEMAND_DIR = ROOT / "data" / "processed" / "electricity_15min"
OUTPUT_DIR = DEMAND_DIR
MILESTONE_YEARS = (2030, 2035, 2040, 2045)
SIM_YEARS = range(2025, 2051)

SECTORS = {
    "cargo": "baseline-cargo-transition-fokush2-risk-neutral",
    "passenger": "baseline-passenger-transition-fokush2-risk-neutral",
    "maritime_cargo": "baseline-maritime-cargo-transition-fokush2-risk-neutral",
}


def realized_scenario_id(case_folder: str) -> str:
    scenario_yaml = ROOT / "data" / "input" / case_folder / "scenario.yaml"
    config = yaml.safe_load(scenario_yaml.read_text())
    return config["ambiguity_aware_decision"]["realized_scenario_id"]


def load_milestone_prices(belief_scenario: str, year: int) -> pd.DataFrame:
    frame = pd.read_csv(
        PRICE_SIGNAL_DIR / f"{belief_scenario}_{year}.csv",
        usecols=["time", "DA_price_EUR_per_MWh"],
    )
    frame["datetime"] = pd.to_datetime(frame["time"])
    return frame[["datetime", "DA_price_EUR_per_MWh"]]


def milestone_for_year(sim_year: int) -> int:
    if sim_year < MILESTONE_YEARS[1]:
        return MILESTONE_YEARS[0]
    for lower, upper in zip(MILESTONE_YEARS, MILESTONE_YEARS[1:]):
        if lower <= sim_year < upper:
            return lower
    return MILESTONE_YEARS[-1]


def transplant_to_year(source: pd.DataFrame, target_year: int) -> pd.DataFrame:
    """Reindexes a real milestone year's 15-min series onto a different
    calendar year, matching by (month, day, hour, minute). Feb 29 in a leap
    target year with a non-leap source is forward-filled from Feb 28."""
    key = (
        source["datetime"].dt.month * 10_000
        + source["datetime"].dt.day * 100
        + source["datetime"].dt.hour * 4
        + source["datetime"].dt.minute // 15
    )
    lookup = source.set_index(key)[["DA_price_EUR_per_MWh"]]
    lookup = lookup[~lookup.index.duplicated(keep="first")]

    target_index = pd.date_range(
        f"{target_year}-01-01", f"{target_year}-12-31 23:45", freq="15min",
    )
    target_key = (
        target_index.month * 10_000 + target_index.day * 100 + target_index.hour * 4
        + target_index.minute // 15
    )
    result = lookup.reindex(target_key).ffill()
    result.index = target_index
    result.index.name = "timestamp"
    return result.reset_index()


def build_case_price_series(belief_scenario: str) -> pd.DataFrame:
    milestone_frames = {year: load_milestone_prices(belief_scenario, year) for year in MILESTONE_YEARS}
    blocks = []
    for sim_year in SIM_YEARS:
        source_year = milestone_for_year(sim_year)
        blocks.append(transplant_to_year(milestone_frames[source_year], sim_year))
    combined = pd.concat(blocks, ignore_index=True)
    combined = combined.rename(columns={"DA_price_EUR_per_MWh": "day_ahead_price_eur_per_mwh"})
    combined["day_ahead_price_eur_per_kwh"] = combined["day_ahead_price_eur_per_mwh"] / 1000.0
    return combined


def export_sector(sector_key: str) -> Path:
    """Keeps demand at its original (hub, fuel-type) granularity -- e.g.
    "Frankfurt Am Main (EDDF) -- E-kerosene (PtL)" stays its own column,
    NOT summed into one Frankfurt total -- because collapsing the
    fuel-type split would make it impossible to see which specific
    electricity-derived fuel's demand a given implied cost belongs to."""
    reference_folder = SECTORS[sector_key]
    demand_path = DEMAND_DIR / f"{sector_key}_electricity_demand_15min.csv.gz"
    demand = pd.read_csv(demand_path)
    demand["timestamp"] = pd.to_datetime(demand["timestamp"])
    demand_columns = [c for c in demand.columns if c not in ("scenario", "timestamp")]

    price_cache: dict[str, pd.DataFrame] = {}
    output_blocks = []
    for case_folder in scenario_sibling_folders(reference_folder):
        scenario_name = case_folder.split("-transition-")[-1]
        belief_scenario = realized_scenario_id(case_folder)
        if belief_scenario not in price_cache:
            price_cache[belief_scenario] = build_case_price_series(belief_scenario)
        prices = price_cache[belief_scenario]

        case_demand = demand[demand["scenario"] == scenario_name]
        if case_demand.empty:
            print(f"  {scenario_name}: no demand rows (skipped)")
            continue

        merged = case_demand[["timestamp", *demand_columns]].merge(prices, on="timestamp", how="left")
        merged = merged.rename(columns={c: f"{c} -- demand_kwh" for c in demand_columns})
        day_ahead_per_kwh = merged["day_ahead_price_eur_per_kwh"].to_numpy()
        for column in demand_columns:
            demand_kwh = merged[f"{column} -- demand_kwh"].to_numpy()
            merged[f"{column} -- day_ahead_cost_eur"] = demand_kwh * day_ahead_per_kwh
        merged.insert(0, "scenario", scenario_name)
        merged.insert(2, "realized_scenario_id", belief_scenario)
        output_blocks.append(merged)
        print(f"  {scenario_name}: realized={belief_scenario}, {len(merged):,} rows")

    combined = pd.concat(output_blocks, ignore_index=True)
    output_path = OUTPUT_DIR / f"{sector_key}_electricity_price_15min.csv"
    combined.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    for sector_key in SECTORS:
        print(f"=== {sector_key} ===")
        path = export_sector(sector_key)
        print(f"  -> {path}\n")


if __name__ == "__main__":
    main()
