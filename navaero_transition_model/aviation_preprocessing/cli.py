from __future__ import annotations

import argparse
from pathlib import Path

from navaero_transition_model.aviation_preprocessing.pipeline import (
    AviationPreprocessingPaths,
    AviationPreprocessingPipeline,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the NATM aviation data-ingestion and preprocessing pipeline.",
    )
    parser.add_argument(
        "--stock-input",
        type=Path,
        required=True,
        help="Path to the source aviation fleet stock CSV.",
    )
    parser.add_argument(
        "--opensky-raw",
        type=Path,
        default=None,
        help="Optional local OpenSky aircraft database CSV. If omitted, the downloader is used.",
    )
    parser.add_argument(
        "--flightlist-folder",
        type=Path,
        default=None,
        help="Optional folder containing monthly OpenSky/Zenodo flightlist CSV/CSV.GZ files.",
    )
    parser.add_argument(
        "--airport-metadata",
        type=Path,
        default=None,
        help=(
            "Optional airport metadata CSV for route distances, allocation, "
            "and country filtering."
        ),
    )
    parser.add_argument(
        "--technology-catalog",
        type=Path,
        default=None,
        help="Optional aviation technology catalog CSV for baseline energy estimation.",
    )
    parser.add_argument(
        "--calibration-input",
        type=Path,
        default=None,
        help="Optional Germany calibration input CSV.",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed/aviation"),
        help="Directory where processed aviation outputs will be written.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pipeline = AviationPreprocessingPipeline(
        paths=AviationPreprocessingPaths(processed_dir=args.processed_dir),
    )
    phase_1_outputs = pipeline.run_phase_1(
        stock_input_path=args.stock_input,
        opensky_raw_path=args.opensky_raw,
    )

    phase_2_outputs: dict[str, Path] = {}
    if args.flightlist_folder is not None and args.airport_metadata is not None:
        phase_2_outputs = pipeline.run_phase_2(
            flightlist_input_folder=args.flightlist_folder,
            airport_metadata_path=args.airport_metadata,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

    phase_3_outputs: dict[str, Path] = {}
    if args.airport_metadata is not None:
        phase_3_outputs = pipeline.run_phase_3(
            stock_input_path=args.stock_input,
            airport_metadata_path=args.airport_metadata,
            technology_catalog_path=args.technology_catalog,
            calibration_input_path=args.calibration_input,
            aircraft_db_processed_path=phase_1_outputs["opensky_aircraft_db_processed"],
        )

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
    raise SystemExit(main())
