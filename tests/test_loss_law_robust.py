from __future__ import annotations

import math

import pandas as pd
import pytest
from navaero_transition_model.core.decision_logic.loss_law_robust import (
    AmbiguityRobustNoValidCandidatesError,
    ProbabilityBounds,
    belief_set_probability_vector,
    construct_probability_bounds,
    mean_probability_vector,
    normalise_probability_table,
    npv_to_loss,
    score_ambiguity_aware_decisions,
    solve_worst_case_expected_shortfall_loss,
    solve_worst_case_mean_loss,
)
from navaero_transition_model.core.scenario import AmbiguityAwareDecisionConfig


def _bounds() -> ProbabilityBounds:
    return ProbabilityBounds(
        scenarios=("S1", "S2", "S3"),
        lower={"S1": 0.10, "S2": 0.30, "S3": 0.20},
        upper={"S1": 0.50, "S2": 0.50, "S3": 0.60},
        min_belief_set={
            "S1": "Electricity_based",
            "S2": "Electricity_based",
            "S3": "Hydrogen_based",
        },
        max_belief_set={"S1": "Conservative", "S2": "Base", "S3": "Electricity_based"},
    )


def test_wide_and_long_probability_inputs_produce_equivalent_bounds() -> None:
    wide = pd.DataFrame(
        {
            "scenario": ["S1", "S2", "S3"],
            "Base": [0.25, 0.50, 0.25],
            "Electricity_based": [0.10, 0.30, 0.60],
            "Hydrogen_based": [0.40, 0.40, 0.20],
            "Conservative": [0.50, 0.30, 0.20],
        },
    )
    long = wide.melt(
        id_vars=["scenario"],
        var_name="belief_set",
        value_name="probability",
    )

    wide_bounds = construct_probability_bounds(normalise_probability_table(wide))
    long_bounds = construct_probability_bounds(normalise_probability_table(long))

    assert wide_bounds.lower == long_bounds.lower
    assert wide_bounds.upper == long_bounds.upper
    assert wide_bounds.to_frame()["scenario"].tolist() == ["S1", "S2", "S3"]
    mean_probabilities = mean_probability_vector(normalise_probability_table(wide))
    assert mean_probabilities == pytest.approx(
        {"S1": 0.3125, "S2": 0.375, "S3": 0.3125},
    )
    base_probabilities = belief_set_probability_vector(
        normalise_probability_table(wide),
        "Base",
    )
    assert base_probabilities == pytest.approx({"S1": 0.25, "S2": 0.50, "S3": 0.25})


def test_probability_parser_rejects_invalid_belief_set_sum() -> None:
    bad = pd.DataFrame(
        {
            "scenario": ["S1", "S2", "S3"],
            "Base": [0.20, 0.20, 0.20],
            "Conservative": [0.50, 0.30, 0.20],
        },
    )

    with pytest.raises(ValueError, match="sum to 1"):
        normalise_probability_table(bad)


def test_deprecated_yaml_risk_metric_is_accepted_with_warning() -> None:
    with pytest.warns(DeprecationWarning, match="risk_metric is deprecated"):
        AmbiguityAwareDecisionConfig.from_dict(
            {
                "enabled": True,
                "scenario_ids": ["S1", "S2", "S3"],
                "probabilities": {"S1": 0.25, "S2": 0.50, "S3": 0.25},
                "risk_metric": "worst_case_mean",
            },
        )


def test_npv_to_loss_and_worst_case_mean_selection() -> None:
    bounds = _bounds()
    npv_matrix = {
        "D1": {"S1": -200.0, "S2": 300.0, "S3": 900.0},
        "D2": {"S1": -50.0, "S2": 350.0, "S3": 750.0},
        "D3": {"S1": -350.0, "S2": 250.0, "S3": 1100.0},
        "D4": {"S1": 100.0, "S2": -200.0, "S3": -600.0},
    }

    robust_npv = {}
    for decision_id, values in npv_matrix.items():
        losses = {scenario: npv_to_loss(npv) for scenario, npv in values.items()}
        result = solve_worst_case_mean_loss(losses, bounds)
        robust_npv[decision_id] = result.robust_worst_npv
        assert sum(result.probabilities.values()) == pytest.approx(1.0)
        for scenario in bounds.scenarios:
            assert (
                bounds.lower[scenario]
                <= result.probabilities[scenario]
                <= bounds.upper[scenario]
            )

    assert robust_npv == pytest.approx(
        {
            "D1": 170.0,
            "D2": 230.0,
            "D3": 120.0,
            "D4": -410.0,
        },
    )
    assert max(robust_npv, key=robust_npv.__getitem__) == "D2"


def test_robust_score_changes_when_bounds_change() -> None:
    losses = {"S1": 200.0, "S2": -300.0, "S3": -900.0}
    original = solve_worst_case_mean_loss(losses, _bounds()).robust_worst_npv
    stressed_bounds = ProbabilityBounds(
        scenarios=("S1", "S2", "S3"),
        lower={"S1": 0.10, "S2": 0.20, "S3": 0.20},
        upper={"S1": 0.70, "S2": 0.50, "S3": 0.60},
        min_belief_set={"S1": "low", "S2": "low", "S3": "low"},
        max_belief_set={"S1": "high", "S2": "high", "S3": "high"},
    )
    stressed = solve_worst_case_mean_loss(losses, stressed_bounds).robust_worst_npv

    assert stressed != pytest.approx(original)


def test_expected_shortfall_penalizes_downside_heavy_loss() -> None:
    bounds = ProbabilityBounds(
        scenarios=("S1", "S2", "S3"),
        lower={"S1": 0.10, "S2": 0.10, "S3": 0.10},
        upper={"S1": 0.80, "S2": 0.80, "S3": 0.80},
        min_belief_set={"S1": "low", "S2": "low", "S3": "low"},
        max_belief_set={"S1": "high", "S2": "high", "S3": "high"},
    )

    downside = solve_worst_case_expected_shortfall_loss(
        {"S1": 100.0, "S2": 0.0, "S3": 0.0},
        bounds,
        tail_alpha=0.80,
    )
    stable = solve_worst_case_expected_shortfall_loss(
        {"S1": 50.0, "S2": 50.0, "S3": 50.0},
        bounds,
        tail_alpha=0.80,
    )

    assert downside.robust_tail_loss > stable.robust_tail_loss
    assert sum(downside.probabilities.values()) == pytest.approx(1.0)
    assert sum(downside.tail_weights.values()) == pytest.approx(1.0)
    beta = 0.20
    for scenario in bounds.scenarios:
        assert beta * downside.tail_weights[scenario] <= downside.probabilities[scenario] + 1e-8


def test_expected_shortfall_matches_bruteforce_grid() -> None:
    bounds = ProbabilityBounds(
        scenarios=("S1", "S2", "S3"),
        lower={"S1": 0.10, "S2": 0.20, "S3": 0.10},
        upper={"S1": 0.60, "S2": 0.70, "S3": 0.50},
        min_belief_set={"S1": "low", "S2": "low", "S3": "low"},
        max_belief_set={"S1": "high", "S2": "high", "S3": "high"},
    )
    losses = {"S1": 90.0, "S2": 30.0, "S3": -10.0}
    tail_alpha = 0.70
    beta = 1.0 - tail_alpha
    deterministic = solve_worst_case_expected_shortfall_loss(
        losses,
        bounds,
        tail_alpha=tail_alpha,
    )

    best = -math.inf
    step = 0.01
    for i in range(0, 101):
        q1 = round(i * step, 2)
        for j in range(0, 101):
            q2 = round(j * step, 2)
            q3 = round(1.0 - q1 - q2, 2)
            q = {"S1": q1, "S2": q2, "S3": q3}
            if abs(sum(q.values()) - 1.0) > 1e-9:
                continue
            if any(q[s] < bounds.lower[s] - 1e-9 or q[s] > bounds.upper[s] + 1e-9 for s in q):
                continue
            best = max(best, _bruteforce_es(losses, q, beta))

    assert deterministic.robust_tail_loss == pytest.approx(best, abs=1e-8)


def test_grouped_scoring_does_not_require_optional_context_columns() -> None:
    bounds = _bounds()
    rows = []
    for operator_id, npv_offset in [("A", 0.0), ("B", 100.0)]:
        for decision_id, values in {
            "D1": {"S1": -200.0, "S2": 300.0, "S3": 900.0},
            "D2": {"S1": -50.0, "S2": 350.0, "S3": 750.0},
        }.items():
            for scenario, npv in values.items():
                rows.append(
                    {
                        "operator_id": operator_id,
                        "decision_id": decision_id,
                        "technology_id": decision_id,
                        "scenario": scenario,
                        "npv": npv + npv_offset,
                    },
                )
    result = score_ambiguity_aware_decisions(
        pd.DataFrame(rows),
        bounds,
        decision_mode="risk_averse_mean",
    )

    assert len(result.selected) == 2
    assert set(result.selected["operator_id"]) == {"A", "B"}
    assert "plant_id" in result.selected.columns


def test_risk_neutral_selects_highest_expected_npv_not_single_scenario_npv() -> None:
    bounds = _bounds()
    rows = []
    for decision_id, values in {
        "high_single": {"S1": 1000.0, "S2": 0.0, "S3": 0.0},
        "high_expected": {"S1": 100.0, "S2": 200.0, "S3": 300.0},
    }.items():
        for scenario, npv in values.items():
            rows.append(
                {
                    "operator_id": "A",
                    "decision_id": decision_id,
                    "technology_id": decision_id,
                    "scenario": scenario,
                    "npv": npv,
                },
            )

    result = score_ambiguity_aware_decisions(
        pd.DataFrame(rows),
        bounds,
        decision_mode="risk_neutral",
        representative_probabilities={"S1": 0.10, "S2": 0.45, "S3": 0.45},
    )

    selected = result.selected.iloc[0]
    assert selected["selected_decision_id"] == "high_expected"
    assert result.scores["expected_npv"].notna().all()


def test_scoring_outputs_all_npv_metrics_for_expected_shortfall() -> None:
    bounds = _bounds()
    rows = []
    for decision_id, values in {
        "D1": {"S1": -200.0, "S2": 300.0, "S3": 900.0},
        "D2": {"S1": -50.0, "S2": 350.0, "S3": 750.0},
    }.items():
        for scenario, npv in values.items():
            rows.append(
                {
                    "operator_id": "A",
                    "decision_id": decision_id,
                    "technology_id": decision_id,
                    "scenario": scenario,
                    "npv": npv,
                },
            )

    result = score_ambiguity_aware_decisions(
        pd.DataFrame(rows),
        bounds,
        decision_mode="risk_averse_expected_shortfall",
        tail_alpha=0.80,
    )

    assert result.scores["robust_worst_case_mean_npv"].notna().all()
    assert result.scores["robust_expected_shortfall_npv"].notna().all()
    assert result.scores["robust_score"].equals(
        result.scores["robust_expected_shortfall_npv"],
    )


def test_risk_averse_mean_selects_highest_robust_worst_case_mean_npv() -> None:
    bounds = _bounds()
    rows = []
    for decision_id, values in {
        "D1": {"S1": -200.0, "S2": 300.0, "S3": 900.0},
        "D2": {"S1": -50.0, "S2": 350.0, "S3": 750.0},
    }.items():
        for scenario, npv in values.items():
            rows.append(
                {
                    "operator_id": "A",
                    "decision_id": decision_id,
                    "technology_id": decision_id,
                    "scenario": scenario,
                    "npv": npv,
                },
            )

    result = score_ambiguity_aware_decisions(
        pd.DataFrame(rows),
        bounds,
        decision_mode="risk_averse_mean",
    )

    assert result.selected.iloc[0]["selected_decision_id"] == "D2"
    assert result.scores["robust_score"].equals(result.scores["robust_worst_case_mean_npv"])


def test_incomplete_candidate_is_excluded_and_no_valid_candidate_raises() -> None:
    bounds = _bounds()
    rows = [
        {
            "operator_id": "A",
            "decision_id": "D1",
            "technology_id": "D1",
            "scenario": scenario,
            "npv": pd.NA,
            "infeasible_reason": "candidate unavailable in scenario",
        }
        for scenario in bounds.scenarios
    ]

    with pytest.raises(AmbiguityRobustNoValidCandidatesError) as exc_info:
        score_ambiguity_aware_decisions(
            pd.DataFrame(rows),
            bounds,
            decision_mode="risk_averse_mean",
        )

    excluded = exc_info.value.excluded_candidates
    assert len(excluded) == 3
    assert set(excluded["reason"]) == {"candidate unavailable in scenario"}


def _bruteforce_es(losses: dict[str, float], q: dict[str, float], beta: float) -> float:
    remaining = beta
    weighted = 0.0
    for scenario in sorted(q, key=lambda item: losses[item], reverse=True):
        take = min(q[scenario], remaining)
        weighted += take * losses[scenario]
        remaining -= take
        if remaining <= 1e-12:
            break
    return weighted / beta
