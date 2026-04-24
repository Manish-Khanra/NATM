from __future__ import annotations

from dashboard_examples.common_case_dashboard import build_case_dashboard
from navaero_transition_model.core.model import NATMModel

Page = build_case_dashboard(
    case_name="baseline-cargo-transition",
    title="NATM Aviation Cargo Dashboard",
    sector_name="aviation",
    application_name="cargo",
    technology_frame_getter=lambda model: NATMModel.to_aviation_technology_frame(model),
    energy_frame_getter=lambda model: NATMModel.to_aviation_energy_emissions_frame(model),
    investment_frame_getter=lambda model: NATMModel.to_aviation_investment_frame(model),
    stock_count_column="aircraft_count",
    stock_axis_label="Aircraft count",
)


if __name__ == "__main__":
    print(
        "Run this dashboard with: "
        "solara run dashboard_examples/aviation_cargo_baseline_dashboard.py",
    )
