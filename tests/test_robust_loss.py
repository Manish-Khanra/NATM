from __future__ import annotations

import pandas as pd
import pytest
from navaero_transition_model.core.result_exports.robust_loss import robust_frontier_loss_summary


def _frontier_frame(*, include_npv: bool = True) -> pd.DataFrame:
    rows = [
        {
            "year": 2025,
            "operator_name": "Airline",
            "asset_id": "1",
            "segment": "short",
            "decision_attitude": "risk_averse",
            "candidate_technology": "cheap",
            "scenario_id": "baseline",
            "scenario_probability": 0.6,
            "candidate_operating_cost": 100.0,
            "candidate_npv": 500.0,
            "selected_flag": True,
            "expected_shortfall_alpha": 0.5,
        },
        {
            "year": 2025,
            "operator_name": "Airline",
            "asset_id": "1",
            "segment": "short",
            "decision_attitude": "risk_averse",
            "candidate_technology": "cheap",
            "scenario_id": "stress",
            "scenario_probability": 0.4,
            "candidate_operating_cost": 300.0,
            "candidate_npv": 200.0,
            "selected_flag": True,
            "expected_shortfall_alpha": 0.5,
        },
        {
            "year": 2025,
            "operator_name": "Airline",
            "asset_id": "1",
            "segment": "short",
            "decision_attitude": "risk_averse",
            "candidate_technology": "stable",
            "scenario_id": "baseline",
            "scenario_probability": 0.6,
            "candidate_operating_cost": 130.0,
            "candidate_npv": 450.0,
            "selected_flag": False,
            "expected_shortfall_alpha": 0.5,
        },
        {
            "year": 2025,
            "operator_name": "Airline",
            "asset_id": "1",
            "segment": "short",
            "decision_attitude": "risk_averse",
            "candidate_technology": "stable",
            "scenario_id": "stress",
            "scenario_probability": 0.4,
            "candidate_operating_cost": 240.0,
            "candidate_npv": 260.0,
            "selected_flag": False,
            "expected_shortfall_alpha": 0.5,
        },
    ]
    frame = pd.DataFrame(rows)
    if not include_npv:
        frame = frame.drop(columns="candidate_npv")
    return frame


def test_robust_loss_summary_uses_cost_regret_against_cheapest_candidate() -> None:
    summary = robust_frontier_loss_summary(_frontier_frame())
    cheap = summary.loc[summary["candidate_technology"].eq("cheap")].iloc[0]

    assert cheap["expected_operating_cost_regret_eur"] == pytest.approx(24.0)
    assert cheap["tail_operating_cost_regret_eur"] == pytest.approx(48.0)


def test_robust_loss_summary_uses_npv_loss_against_highest_npv_candidate() -> None:
    summary = robust_frontier_loss_summary(_frontier_frame())
    stable = summary.loc[summary["candidate_technology"].eq("stable")].iloc[0]

    assert stable["expected_npv_loss_eur"] == pytest.approx(30.0)
    assert stable["tail_npv_loss_eur"] == pytest.approx(50.0)


def test_robust_loss_summary_handles_missing_npv() -> None:
    summary = robust_frontier_loss_summary(_frontier_frame(include_npv=False))

    assert not summary.empty
    assert summary["expected_npv_loss_eur"].isna().all()
    assert summary["tail_npv_loss_eur"].isna().all()
