from __future__ import annotations

import argparse
from pathlib import Path

from natm.core.model import NATMModel
from natm.core.scenario import NATMScenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NATM starter simulation.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.yaml"),
        help="Path to the YAML scenario file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional CSV file path for simulation history.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenario = NATMScenario.from_yaml(args.config)
    model = NATMModel(scenario)
    history = model.run()
    summary = model.to_frame()

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(args.output, index=False)

    final_row = summary.iloc[-1]
    print(f"Scenario: {scenario.name}")
    print(f"Years simulated: {len(history)}")
    print(f"Final carbon price: {final_row['carbon_price']:.2f}")
    print(
        "Final shares: "
        f"aviation={final_row['aviation_alternative_share']:.2%}, "
        f"maritime={final_row['maritime_alternative_share']:.2%}"
    )
    print(
        "Final transition pressure: "
        f"aviation={final_row['aviation_transition_pressure']:.2%}, "
        f"maritime={final_row['maritime_transition_pressure']:.2%}"
    )
    return 0
