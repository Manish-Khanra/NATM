from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
CASE_ROOT = PROJECT_ROOT / "data"
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

if TYPE_CHECKING:
    from natm.core.model import NATMModel
    from natm.core.scenario import NATMScenario

# Define the available named simulations here.
AVAILABLE_EXAMPLES = {
    "small_with_aviation_passenger": {
        "case": "baseline-transition",
        "description": "Baseline aviation-passenger Mesa case.",
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a NATM case and write outputs into outputs/<selected_example>/.",
    )
    parser.add_argument(
        "--example",
        default=None,
        choices=sorted(AVAILABLE_EXAMPLES),
        help="Optional named example override.",
    )
    parser.add_argument(
        "--case",
        default=None,
        help="Optional direct case folder override under data/.",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Optional custom output folder name under outputs/.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip writing the model summary CSV.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Skip writing the detailed output CSV files.",
    )
    parser.add_argument(
        "--no-sqlite",
        action="store_true",
        help="Skip writing the SQLite output database.",
    )
    return parser


def create_output_folder(output_name: str) -> Path:
    output_dir = OUTPUT_ROOT / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def export_run_outputs(
    *,
    model: NATMModel,
    scenario: NATMScenario,
    output_dir: Path,
    export_summary: bool,
    export_details: bool,
    export_sqlite: bool,
) -> Path | None:
    from natm.core.outputs import DetailedOutputWriter
    from natm.core.storage import SQLiteSimulationStore

    summary = model.to_frame()
    sqlite_path: Path | None = None

    if export_summary:
        summary.to_csv(output_dir / "model_summary.csv", index=False)
    if export_details:
        DetailedOutputWriter().export(model, output_dir)
    if export_sqlite:
        sqlite_store = SQLiteSimulationStore(output_dir / "natm_runs.sqlite")
        sqlite_store.write_run(model, scenario)
        sqlite_path = sqlite_store.database_path

    return sqlite_path


def run_named_example(
    *,
    example_name: str,
    case_name: str | None = None,
    output_name: str | None = None,
    export_summary: bool = True,
    export_details: bool = True,
    export_sqlite: bool = True,
) -> int:
    try:
        from natm.cli import resolve_case_config
        from natm.core.model import NATMModel
        from natm.core.scenario import NATMScenario
    except ModuleNotFoundError as exc:
        if exc.name == "mesa":
            raise SystemExit(
                "Mesa is not available in this interpreter. Select the NATM .venv in VS Code "
                "or run `.venv\\Scripts\\python.exe run.py`.",
            ) from exc
        raise

    selected_case = case_name or str(AVAILABLE_EXAMPLES[example_name]["case"])
    config_path = resolve_case_config(selected_case)
    scenario = NATMScenario.from_yaml(config_path)
    model = NATMModel(scenario)
    history = model.run()

    selected_output_name = output_name or example_name
    output_dir = create_output_folder(selected_output_name)
    sqlite_path = export_run_outputs(
        model=model,
        scenario=scenario,
        output_dir=output_dir,
        export_summary=export_summary,
        export_details=export_details,
        export_sqlite=export_sqlite,
    )

    summary = model.to_frame()
    final_row = summary.iloc[-1]
    final_shares = ", ".join(
        f"{sector}={final_row[f'{sector}_alternative_share']:.2%}"
        for sector in scenario.enabled_sectors
    )
    final_transition_pressures = ", ".join(
        f"{sector}={final_row[f'{sector}_transition_pressure']:.2%}"
        for sector in scenario.enabled_sectors
    )

    print(f"Example: {example_name}")
    print(f"Scenario: {scenario.name}")
    print(f"Case: {selected_case}")
    print(f"Config: {config_path}")
    print(f"Output folder: {output_dir}")
    print(f"Enabled sectors: {', '.join(scenario.enabled_sectors)}")
    print(f"Years simulated: {len(history)}")
    print(f"Final carbon price: {final_row['carbon_price']:.2f}")
    print(f"Final shares: {final_shares}")
    print(f"Final transition pressure: {final_transition_pressures}")
    if export_summary:
        print(f"Summary CSV: {output_dir / 'model_summary.csv'}")
    if export_details:
        print(f"Detail CSVs: {output_dir}")
    if sqlite_path is not None:
        print(f"SQLite output: {sqlite_path}")
    return 0


if __name__ == "__main__":
    """
    Available examples:
    - small_with_aviation_passenger: baseline aviation-passenger Mesa case

    The easiest way to use this script in VS Code is to edit the small
    configuration block below and then press Run on run.py.
    """

    logging.basicConfig(level=logging.INFO)

    # Select the named example to run from AVAILABLE_EXAMPLES above.
    selected_example = "small_with_aviation_passenger"

    # Optional direct case override. Keep as None to use the case from the example.
    selected_case = None

    # Optional output folder name under outputs/. Keep as None to use selected_example.
    output_name = None

    # Choose which outputs to write into outputs/<selected_example>/.
    export_summary = True
    export_details = True
    export_sqlite = True

    # Command-line flags can still override the values above if you want.
    args = build_parser().parse_args()
    if args.example is not None:
        selected_example = args.example
    if args.case is not None:
        selected_case = args.case
    if args.output_name is not None:
        output_name = args.output_name
    if args.no_summary:
        export_summary = False
    if args.no_details:
        export_details = False
    if args.no_sqlite:
        export_sqlite = False

    raise SystemExit(
        run_named_example(
            example_name=selected_example,
            case_name=selected_case,
            output_name=output_name,
            export_summary=export_summary,
            export_details=export_details,
            export_sqlite=export_sqlite,
        ),
    )
