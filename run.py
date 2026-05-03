from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "simulation_results"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from navaero_transition_model.core.model import NATMModel
    from navaero_transition_model.core.scenario import (
        AviationPreprocessingConfig,
        NATMScenario,
    )

log = logging.getLogger(__name__)

AVAILABLE_EXAMPLES = {
    "small_with_aviation_passenger": {
        "case": "baseline-passenger-transition",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a NATM simulation case or scenario-defined preprocessing run.",
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

    openap_group = parser.add_mutually_exclusive_group()
    openap_group.add_argument(
        "--estimate-openap-fuel",
        dest="estimate_openap_fuel",
        action="store_true",
        default=None,
        help="Override scenario.yaml and enable OpenAP fuel/emissions preprocessing.",
    )
    openap_group.add_argument(
        "--no-estimate-openap-fuel",
        dest="estimate_openap_fuel",
        action="store_false",
        help="Override scenario.yaml and disable OpenAP fuel/emissions preprocessing.",
    )
    parser.add_argument(
        "--openap-mode",
        choices=("synthetic", "trajectory", "auto"),
        default=None,
        help="Optional OpenAP estimation mode override.",
    )
    parser.add_argument(
        "--route-extension-factor",
        type=float,
        default=None,
        help="Optional route extension factor override for OpenAP synthetic missions.",
    )
    non_co2_group = parser.add_mutually_exclusive_group()
    non_co2_group.add_argument(
        "--include-non-co2",
        dest="include_non_co2",
        action="store_true",
        default=None,
        help="Override scenario.yaml and include non-CO2 OpenAP emissions where available.",
    )
    non_co2_group.add_argument(
        "--no-include-non-co2",
        dest="include_non_co2",
        action="store_false",
        help="Override scenario.yaml and estimate CO2 only in OpenAP preprocessing.",
    )
    return parser


def selected_case_name(example_name: str, case_name: str | None) -> str:
    return case_name or str(AVAILABLE_EXAMPLES[example_name]["case"])


def scenario_path_for_case(case_name: str) -> Path:
    from navaero_transition_model.cli import resolve_case_config

    return resolve_case_config(case_name)


def load_scenario_for_case(case_name: str) -> NATMScenario:
    from navaero_transition_model.core.scenario import NATMScenario

    return NATMScenario.from_yaml(scenario_path_for_case(case_name))


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

    sqlite_path: Path | None = None
    if export_summary:
        model.to_frame().to_csv(output_dir / "model_summary.csv", index=False)
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
        from navaero_transition_model.core.model import NATMModel
    except ModuleNotFoundError as exc:
        if exc.name == "mesa":
            raise SystemExit(
                "Mesa is not available in this interpreter. Select the NATM .venv in VS Code "
                "or run `.venv\\Scripts\\python.exe run.py`.",
            ) from exc
        raise

    selected_case = selected_case_name(example_name, case_name)
    scenario = load_scenario_for_case(selected_case)
    model = NATMModel(scenario)
    history = model.run()
    output_dir = create_output_folder(output_name or example_name)
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
    print(f"Config: {scenario_path_for_case(selected_case)}")
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


def _require_path(
    scenario: NATMScenario,
    config: AviationPreprocessingConfig,
    field_name: str,
) -> Path:
    path = config.resolve_path(scenario.base_path, field_name)
    if path is None:
        raise SystemExit(f"preprocessing.aviation.{field_name} must be set in scenario.yaml.")
    return path


def _apply_openap_overrides(
    config: AviationPreprocessingConfig,
    *,
    estimate_openap_fuel: bool | None,
    openap_mode: str | None,
    route_extension_factor: float | None,
    include_non_co2: bool | None,
) -> AviationPreprocessingConfig:
    openap = config.openap
    if estimate_openap_fuel is not None:
        openap = replace(openap, estimate_fuel=estimate_openap_fuel)
    if openap_mode is not None:
        openap = replace(openap, mode=openap_mode)
    if route_extension_factor is not None:
        openap = replace(openap, route_extension_factor=route_extension_factor)
    if include_non_co2 is not None:
        openap = replace(openap, include_non_co2=include_non_co2)
    return replace(config, openap=openap)


def run_aviation_preprocessing_from_scenario(
    *,
    example_name: str,
    case_name: str | None = None,
    estimate_openap_fuel: bool | None = None,
    openap_mode: str | None = None,
    route_extension_factor: float | None = None,
    include_non_co2: bool | None = None,
) -> int:
    from navaero_transition_model.aviation_preprocessing.openap_backend import OpenAPFuelConfig
    from navaero_transition_model.aviation_preprocessing.pipeline import (
        AviationPreprocessingPaths,
        AviationPreprocessingPipeline,
    )

    selected_case = selected_case_name(example_name, case_name)
    scenario = load_scenario_for_case(selected_case)
    preprocessing_config = scenario.aviation_preprocessing_config()
    if preprocessing_config is None or not preprocessing_config.enabled:
        raise SystemExit(
            f"Case '{selected_case}' has no enabled preprocessing.aviation block in scenario.yaml.",
        )

    preprocessing_config = _apply_openap_overrides(
        preprocessing_config,
        estimate_openap_fuel=estimate_openap_fuel,
        openap_mode=openap_mode,
        route_extension_factor=route_extension_factor,
        include_non_co2=include_non_co2,
    )
    stock_input = _require_path(scenario, preprocessing_config, "stock_input")
    processed_dir = _require_path(scenario, preprocessing_config, "processed_dir")
    opensky_raw = preprocessing_config.resolve_path(scenario.base_path, "opensky_raw")
    flightlist_folder = preprocessing_config.resolve_path(
        scenario.base_path,
        "flightlist_folder",
    )
    airport_metadata = preprocessing_config.resolve_path(scenario.base_path, "airport_metadata")
    technology_catalog = preprocessing_config.resolve_path(
        scenario.base_path,
        "technology_catalog",
    )
    calibration_input = preprocessing_config.resolve_path(
        scenario.base_path,
        "calibration_input",
    )

    pipeline = AviationPreprocessingPipeline(
        paths=AviationPreprocessingPaths(processed_dir=processed_dir),
    )
    phase_1_outputs = pipeline.run_phase_1(
        stock_input_path=stock_input,
        opensky_raw_path=opensky_raw,
    )

    phase_2_outputs: dict[str, Path] = {}
    if flightlist_folder is not None and airport_metadata is not None:
        phase_2_outputs = pipeline.run_phase_2(
            flightlist_input_folder=flightlist_folder,
            airport_metadata_path=airport_metadata,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

    phase_3_outputs: dict[str, Path] = {}
    if airport_metadata is not None:
        phase_3_outputs = pipeline.run_phase_3(
            stock_input_path=phase_1_outputs["enriched_stock"],
            airport_metadata_path=airport_metadata,
            technology_catalog_path=technology_catalog,
            calibration_input_path=calibration_input,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

    openap_outputs: dict[str, Path] = {}
    if preprocessing_config.openap.estimate_fuel:
        if flightlist_folder is None or airport_metadata is None:
            raise SystemExit(
                "OpenAP preprocessing requires preprocessing.aviation.flightlist_folder "
                "and preprocessing.aviation.airport_metadata.",
            )
        openap_outputs = pipeline.run_openap_fuel_estimation(
            airport_metadata_path=airport_metadata,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
            fleet_stock_path=phase_1_outputs["enriched_stock"],
            technology_catalog_path=technology_catalog,
            scenario_table_path=scenario.base_path / "aviation_scenario.csv",
            application_name=(scenario.applications_for_sector("aviation") or ("passenger",))[0],
            openap_mode=preprocessing_config.openap.mode,
            config=OpenAPFuelConfig(
                route_extension_factor=preprocessing_config.openap.route_extension_factor,
                include_non_co2=preprocessing_config.openap.include_non_co2,
            ),
        )

    print(f"Preprocessing case: {selected_case}")
    print(f"Scenario: {scenario.name}")
    print(f"Config: {scenario_path_for_case(selected_case)}")
    print(f"Processed output directory: {processed_dir}")
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
    if openap_outputs:
        print("OpenAP fuel/emissions outputs:")
        for label, path in openap_outputs.items():
            print(f"  {label}: {path}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)

    # Edit these two values when running from VS Code.
    selected_mode = "simulation"
    selected_example = "small_with_aviation_passenger"

    selected_case = None
    output_name = None
    export_summary = True
    export_details = True
    export_sqlite = True

    args = build_parser().parse_args()
    if args.mode is not None:
        selected_mode = args.mode
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

    if selected_mode == "aviation_preprocessing":
        return run_aviation_preprocessing_from_scenario(
            example_name=selected_example,
            case_name=selected_case,
            estimate_openap_fuel=args.estimate_openap_fuel,
            openap_mode=args.openap_mode,
            route_extension_factor=args.route_extension_factor,
            include_non_co2=args.include_non_co2,
        )

    return run_named_example(
        example_name=selected_example,
        case_name=selected_case,
        output_name=output_name,
        export_summary=export_summary,
        export_details=export_details,
        export_sqlite=export_sqlite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
