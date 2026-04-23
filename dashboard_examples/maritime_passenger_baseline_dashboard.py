from __future__ import annotations

from dashboard_examples.common_case_dashboard import build_case_dashboard
from navaero_transition_model.core.model import NATMModel

page = build_case_dashboard(
    case_name="baseline-maritime-passenger-transition",
    title="NATM Maritime Passenger Dashboard",
    sector_name="maritime",
    application_name="passenger",
    technology_frame_getter=lambda model: NATMModel.to_maritime_technology_frame(model),
    energy_frame_getter=lambda model: NATMModel.to_maritime_energy_emissions_frame(model),
    investment_frame_getter=lambda model: NATMModel.to_maritime_investment_frame(model),
    stock_count_column="vessel_count",
    stock_axis_label="Vessel count",
)


if __name__ == "__main__":
    print(
        "Run this dashboard with: "
        "solara run dashboard_examples/maritime_passenger_baseline_dashboard.py",
    )
