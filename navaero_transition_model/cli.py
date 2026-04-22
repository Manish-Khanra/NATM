from __future__ import annotations

import argparse
from pathlib import Path

from navaero_transition_model.core.database import SQLiteSimulationStore
from navaero_transition_model.core.model import NATMModel
from navaero_transition_model.core.result_exports import DetailedOutputWriter
from navaero_transition_model.core.scenario import NATMScenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = PROJECT_ROOT / "data"


def resolve_case_config(case_name: str) -> Path:
    return CASE_ROOT / case_name / "scenario.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NATM starter simulation.")
    parser.add_argument(
        "--case",
        default="baseline-transition",
        help="Case folder name under data/ to run.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional explicit path to a YAML scenario file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional CSV file path for simulation history.",
    )
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=None,
        help="Optional directory for detailed Mesa output tables.",
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=None,
        help="Optional SQLite database path for storing case inputs and run outputs.",
    )
    return parser


def export_detailed_outputs(model: NATMModel, output_dir: Path) -> None:
    DetailedOutputWriter().export(model, output_dir)


def main() -> int:
    args = build_parser().parse_args()
    config_path = args.config or resolve_case_config(args.case)
    scenario = NATMScenario.from_yaml(config_path)
    model = NATMModel(scenario)
    history = model.run()
    summary = model.to_frame()
    sqlite_store = None

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(args.output, index=False)
    if args.details_dir is not None:
        export_detailed_outputs(model, args.details_dir)
    if args.sqlite_db is not None:
        sqlite_store = SQLiteSimulationStore(args.sqlite_db)
        sqlite_store.write_run(model, scenario)

    final_row = summary.iloc[-1]
    final_shares = ", ".join(
        f"{sector}={final_row[f'{sector}_alternative_share']:.2%}"
        for sector in scenario.enabled_sectors
    )
    final_transition_pressures = ", ".join(
        f"{sector}={final_row[f'{sector}_transition_pressure']:.2%}"
        for sector in scenario.enabled_sectors
    )

    print(f"Scenario: {scenario.name}")
    print(f"Config: {config_path}")
    print(f"Enabled sectors: {', '.join(scenario.enabled_sectors)}")
    print(f"Years simulated: {len(history)}")
    print(f"Final carbon price: {final_row['carbon_price']:.2f}")
    print(f"Final shares: {final_shares}")
    print(f"Final transition pressure: {final_transition_pressures}")
    if sqlite_store is not None:
        print(f"SQLite output: {sqlite_store.database_path}")
    return 0
