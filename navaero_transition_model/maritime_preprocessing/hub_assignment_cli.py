from __future__ import annotations

import argparse
from pathlib import Path

from navaero_transition_model.maritime_preprocessing.hub_assignment import apply_hub_assignment

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT_VISITS = (
    REPO_ROOT / "data" / "archive" / "maritime" / "AIS" / "gfw_port_visits_2024.csv"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replace a maritime fleet-stock CSV's placeholder `Main Hub` value with each "
            "vessel's real home port, derived from Global Fishing Watch AIS port-visit "
            "history (the German port where it spent the most total tracked time)."
        ),
    )
    parser.add_argument(
        "--fleet-stock",
        required=True,
        type=Path,
        nargs="+",
        help="One or more maritime_fleet_stock.csv paths to update in place.",
    )
    parser.add_argument(
        "--port-visits",
        type=Path,
        default=DEFAULT_PORT_VISITS,
        help=f"AIS port-visit CSV. Defaults to {DEFAULT_PORT_VISITS}.",
    )
    parser.add_argument(
        "--fallback-hub",
        default="Hamburg",
        help="Home port assigned to vessels with no recorded German port visit "
        "(tagged as such in the new main_hub_match_method column). Default: Hamburg.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    for fleet_stock_path in args.fleet_stock:
        updated = apply_hub_assignment(
            fleet_stock_path,
            args.port_visits,
            fallback_hub=args.fallback_hub,
        )
        matched = (
            updated["main_hub_match_method"] == "ais_port_visits_2024_duration_weighted"
        ).sum()
        print(
            f"{fleet_stock_path}: {matched}/{len(updated)} vessels matched to a real "
            "AIS home port",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
