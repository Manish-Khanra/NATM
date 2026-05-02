from __future__ import annotations

import argparse
from pathlib import Path

from navaero_transition_model.postprocessing.airport_fuel_allocation import (
    AirportFuelAllocationConfig,
    allocate_airport_fuel,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Allocate simulated aviation fuel demand to airports as a postprocess.",
    )
    parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="Simulation result folder containing aircraft.csv.",
    )
    parser.add_argument(
        "--processed-aviation-dir",
        type=Path,
        default=None,
        help="Processed aviation folder with OpenAP flight/route outputs.",
    )
    parser.add_argument(
        "--airport-metadata",
        type=Path,
        default=None,
        help="Airport metadata CSV with IATA and coordinates.",
    )
    parser.add_argument(
        "--technology-catalog",
        type=Path,
        default=None,
        help="Optional aviation technology catalog for fuel_capacity_kwh.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to --results.",
    )
    parser.add_argument(
        "--reserve-factor",
        type=float,
        default=1.15,
        help="Departure fuel target factor used for exact flightlist sequences.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    defaults = AirportFuelAllocationConfig(results_dir=args.results)
    config = AirportFuelAllocationConfig(
        results_dir=args.results,
        processed_aviation_dir=args.processed_aviation_dir or defaults.processed_aviation_dir,
        airport_metadata_path=args.airport_metadata or defaults.airport_metadata_path,
        technology_catalog_path=args.technology_catalog,
        output_dir=args.output_dir,
        reserve_factor=args.reserve_factor,
    )
    outputs = allocate_airport_fuel(config)
    output_dir = config.output_dir or config.results_dir
    print(f"Airport fuel demand: {output_dir / 'airport_fuel_demand.csv'}")
    print(f"Route energy flow: {output_dir / 'route_energy_flow.csv'}")
    print(f"Allocation summary: {output_dir / 'airport_fuel_allocation_summary.csv'}")
    if not outputs.allocation_summary.empty:
        print(outputs.allocation_summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
