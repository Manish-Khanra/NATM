from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
CASE_ROOT = PROJECT_ROOT / "data"
OUTPUT_ROOT = PROJECT_ROOT / "simulation_results"
SRC_ROOT = PROJECT_ROOT

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

if TYPE_CHECKING:
    from navaero_transition_model.core.model import NATMModel
    from navaero_transition_model.core.scenario import NATMScenario

# Define the available named simulations here.
AVAILABLE_EXAMPLES = {
    "small_with_aviation_passenger": {
        "case": "baseline-transition",
        "description": "Baseline aviation-passenger Mesa case.",
    },
    "small_with_aviation_cargo": {
        "case": "baseline-cargo-transition",
        "description": "Baseline aviation-cargo Mesa case.",
    },
    "small_with_maritime_cargo": {
        "case": "baseline-maritime-cargo-transition",
        "description": "Baseline maritime-cargo Mesa case.",
    },
    "small_with_maritime_passenger": {
        "case": "baseline-maritime-passenger-transition",
        "description": "Baseline maritime-passenger Mesa case.",
    },
}

AVAILABLE_PREPROCESSING_EXAMPLES = {
    "synthetic_aviation_preprocessing": {
        "description": "Synthetic aviation preprocessing example using local sample data.",
        "stock_input": "data/baseline-transition/aviation_fleet_stock.csv",
        "opensky_raw": "data/examples/aviation_preprocessing/opensky_aircraft_db_sample.csv",
        "flightlist_folder": "data/examples/aviation_preprocessing/opensky_flightlists",
        "airport_metadata": "data/examples/aviation_preprocessing/airports_sample.csv",
        "technology_catalog": "data/baseline-transition/aviation_technology_catalog.csv",
        "calibration_input": "data/examples/aviation_preprocessing/germany_calibration_input.csv",
        "processed_dir": "data/processed/aviation",
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Launch a NATM simulation case or aviation preprocessing example."),
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=("simulation", "aviation_preprocessing"),
        help="Optional launcher mode override.",
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
        help="Optional custom output folder name under simulation_results/.",
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
    parser.add_argument(
        "--preprocess-example",
        default=None,
        choices=sorted(AVAILABLE_PREPROCESSING_EXAMPLES),
        help="Optional named aviation preprocessing example override.",
    )
    parser.add_argument(
        "--stock-input",
        default=None,
        help="Optional stock CSV override for aviation preprocessing mode.",
    )
    parser.add_argument(
        "--opensky-raw",
        default=None,
        help="Optional local OpenSky aircraft database CSV override.",
    )
    parser.add_argument(
        "--flightlist-folder",
        default=None,
        help="Optional monthly OpenSky/Zenodo flightlist folder override.",
    )
    parser.add_argument(
        "--airport-metadata",
        default=None,
        help="Optional airport metadata CSV override for preprocessing mode.",
    )
    parser.add_argument(
        "--technology-catalog",
        default=None,
        help="Optional aviation technology catalog CSV override for preprocessing mode.",
    )
    parser.add_argument(
        "--calibration-input",
        default=None,
        help="Optional calibration input CSV override for preprocessing mode.",
    )
    parser.add_argument(
        "--processed-dir",
        default=None,
        help="Optional processed output directory override for preprocessing mode.",
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
    from navaero_transition_model.core.database import SQLiteSimulationStore
    from navaero_transition_model.core.result_exports import DetailedOutputWriter

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
        from navaero_transition_model.cli import resolve_case_config
        from navaero_transition_model.core.model import NATMModel
        from navaero_transition_model.core.scenario import NATMScenario
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


def _resolve_optional_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return (PROJECT_ROOT / value).resolve()


def run_preprocessing_example(
    *,
    example_name: str,
    stock_input: str | None = None,
    opensky_raw: str | None = None,
    flightlist_folder: str | None = None,
    airport_metadata: str | None = None,
    technology_catalog: str | None = None,
    calibration_input: str | None = None,
    processed_dir: str | None = None,
) -> int:
    from navaero_transition_model.aviation_preprocessing.pipeline import (
        AviationPreprocessingPaths,
        AviationPreprocessingPipeline,
    )

    preset = AVAILABLE_PREPROCESSING_EXAMPLES[example_name]
    resolved_stock_input = _resolve_optional_path(stock_input or preset["stock_input"])
    if resolved_stock_input is None:
        raise SystemExit("Aviation preprocessing requires a stock_input path.")
    resolved_opensky_raw = _resolve_optional_path(opensky_raw or preset.get("opensky_raw"))
    resolved_flightlist_folder = _resolve_optional_path(
        flightlist_folder or preset.get("flightlist_folder"),
    )
    resolved_airport_metadata = _resolve_optional_path(
        airport_metadata or preset.get("airport_metadata"),
    )
    resolved_technology_catalog = _resolve_optional_path(
        technology_catalog or preset.get("technology_catalog"),
    )
    resolved_calibration_input = _resolve_optional_path(
        calibration_input or preset.get("calibration_input"),
    )
    resolved_processed_dir = _resolve_optional_path(processed_dir or preset["processed_dir"])
    if resolved_processed_dir is None:
        raise SystemExit("Aviation preprocessing requires a processed_dir path.")

    pipeline = AviationPreprocessingPipeline(
        paths=AviationPreprocessingPaths(processed_dir=resolved_processed_dir),
    )
    phase_1_outputs = pipeline.run_phase_1(
        stock_input_path=resolved_stock_input,
        opensky_raw_path=resolved_opensky_raw,
    )

    phase_2_outputs: dict[str, Path] = {}
    if resolved_flightlist_folder is not None and resolved_airport_metadata is not None:
        phase_2_outputs = pipeline.run_phase_2(
            flightlist_input_folder=resolved_flightlist_folder,
            airport_metadata_path=resolved_airport_metadata,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

    phase_3_outputs: dict[str, Path] = {}
    if resolved_airport_metadata is not None:
        phase_3_outputs = pipeline.run_phase_3(
            stock_input_path=phase_1_outputs["enriched_stock"],
            airport_metadata_path=resolved_airport_metadata,
            technology_catalog_path=resolved_technology_catalog,
            calibration_input_path=resolved_calibration_input,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

    print(f"Preprocessing example: {example_name}")
    print(f"Processed output directory: {resolved_processed_dir}")
    print("Phase 1 outputs:")
    for label, path in phase_1_outputs.items():
        print(f"  {label}: {path}")
    if phase_2_outputs:
        print("Phase 2 outputs:")
        for label, path in phase_2_outputs.items():
            print(f"  {label}: {path}")
    if phase_3_outputs:
        print("Phase 3 outputs:")
        for label, path in phase_3_outputs.items():
            print(f"  {label}: {path}")
    return 0


if __name__ == "__main__":
    """
    Available examples:
    - small_with_aviation_passenger: baseline aviation-passenger Mesa case
    - small_with_aviation_cargo: baseline aviation-cargo Mesa case
    - small_with_maritime_cargo: baseline maritime-cargo Mesa case
    - small_with_maritime_passenger: baseline maritime-passenger Mesa case
    - synthetic_aviation_preprocessing: synthetic aviation preprocessing workflow

    The easiest way to use this script in VS Code is to edit the small
    configuration block below and then press Run on run.py.
    """

    logging.basicConfig(level=logging.INFO)

    # Select the launcher mode: "simulation" or "aviation_preprocessing".
    selected_mode = "simulation"

    # Select the named example to run from AVAILABLE_EXAMPLES above.
    selected_example = "small_with_aviation_passenger"

    # Select the named preprocessing example from AVAILABLE_PREPROCESSING_EXAMPLES above.
    selected_preprocessing_example = "synthetic_aviation_preprocessing"

    # Optional direct case override. Keep as None to use the case from the example.
    selected_case = None

    # Optional output folder name under simulation_results/. Keep as None to use selected_example.
    output_name = None

    # Choose which outputs to write into simulation_results/<selected_example>/.
    export_summary = True
    export_details = True
    export_sqlite = True

    # Optional preprocessing overrides. Keep as None to use the selected preprocessing preset.
    preprocessing_stock_input = None
    preprocessing_opensky_raw = None
    preprocessing_flightlist_folder = None
    preprocessing_airport_metadata = None
    preprocessing_technology_catalog = None
    preprocessing_calibration_input = None
    preprocessing_processed_dir = None

    # Command-line flags can still override the values above if you want.
    args = build_parser().parse_args()
    if args.mode is not None:
        selected_mode = args.mode
    if args.example is not None:
        selected_example = args.example
    if args.preprocess_example is not None:
        selected_preprocessing_example = args.preprocess_example
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
    if args.stock_input is not None:
        preprocessing_stock_input = args.stock_input
    if args.opensky_raw is not None:
        preprocessing_opensky_raw = args.opensky_raw
    if args.flightlist_folder is not None:
        preprocessing_flightlist_folder = args.flightlist_folder
    if args.airport_metadata is not None:
        preprocessing_airport_metadata = args.airport_metadata
    if args.technology_catalog is not None:
        preprocessing_technology_catalog = args.technology_catalog
    if args.calibration_input is not None:
        preprocessing_calibration_input = args.calibration_input
    if args.processed_dir is not None:
        preprocessing_processed_dir = args.processed_dir

    if selected_mode == "aviation_preprocessing":
        raise SystemExit(
            run_preprocessing_example(
                example_name=selected_preprocessing_example,
                stock_input=preprocessing_stock_input,
                opensky_raw=preprocessing_opensky_raw,
                flightlist_folder=preprocessing_flightlist_folder,
                airport_metadata=preprocessing_airport_metadata,
                technology_catalog=preprocessing_technology_catalog,
                calibration_input=preprocessing_calibration_input,
                processed_dir=preprocessing_processed_dir,
            ),
        )

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
