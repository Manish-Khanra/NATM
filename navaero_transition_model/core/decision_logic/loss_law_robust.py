from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog

KNOWN_WIDE_METADATA_COLUMNS = {
    "scenario",
    "scenario_id",
    "description",
    "year",
    "category",
}

CONTEXT_COLUMNS = (
    "plant_id",
    "operator_id",
    "operator_name",
    "asset_id",
    "aircraft_id",
    "vessel_id",
    "decision_year",
)

ACTIVE_LOSS_LAW_DECISION_MODES = (
    "risk_neutral",
    "risk_averse_mean",
    "risk_averse_expected_shortfall",
    "minimax_regret",
)

OUTPUT_CONTEXT_COLUMNS = (
    "plant_id",
    "operator_id",
    "operator_name",
    "asset_id",
    "aircraft_id",
    "vessel_id",
    "decision_year",
)


@dataclass(frozen=True)
class ProbabilityBounds:
    scenarios: tuple[str, ...]
    lower: dict[str, float]
    upper: dict[str, float]
    min_belief_set: dict[str, str]
    max_belief_set: dict[str, str]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "scenario": scenario,
                    "p_lower": self.lower[scenario],
                    "p_upper": self.upper[scenario],
                    "min_belief_set": self.min_belief_set[scenario],
                    "max_belief_set": self.max_belief_set[scenario],
                }
                for scenario in self.scenarios
            ],
        )


@dataclass(frozen=True)
class RobustMetricResult:
    robust_mean_loss: float | None
    robust_worst_npv: float | None
    robust_tail_loss: float | None
    robust_tail_npv: float | None
    probabilities: dict[str, float]
    tail_weights: dict[str, float]


@dataclass(frozen=True)
class AmbiguityScoreResult:
    scores: pd.DataFrame
    selected: pd.DataFrame
    worst_case_probabilities: pd.DataFrame
    excluded_candidates: pd.DataFrame


class AmbiguityRobustNoValidCandidatesError(ValueError):
    """Raised when robust loss-law scoring has no complete candidate to select."""

    def __init__(self, message: str, excluded_candidates: pd.DataFrame) -> None:
        super().__init__(message)
        self.excluded_candidates = excluded_candidates.copy()


def load_belief_set_probabilities(
    path: str | Path,
    *,
    belief_sets: tuple[str, ...] = (),
    input_format: str = "auto",
    tolerance: float = 1e-8,
) -> pd.DataFrame:
    probability_path = Path(path)
    if not probability_path.exists():
        raise ValueError(f"Ambiguity probability table not found: {probability_path}")
    dataframe = pd.read_csv(probability_path)
    return normalise_probability_table(
        dataframe,
        belief_sets=belief_sets,
        input_format=input_format,
        tolerance=tolerance,
    )


def normalise_probability_table(
    dataframe: pd.DataFrame,
    *,
    belief_sets: tuple[str, ...] = (),
    input_format: str = "auto",
    tolerance: float = 1e-8,
) -> pd.DataFrame:
    if dataframe.empty:
        raise ValueError("Ambiguity probability table has no rows")

    normalized_format = input_format.strip().lower()
    if normalized_format not in {"auto", "wide", "long"}:
        raise ValueError(
            "ambiguity_aware_decision.probability_input_format must be auto, wide, or long",
        )

    columns = set(dataframe.columns)
    if "scenario" not in columns and "scenario_id" in columns:
        dataframe = dataframe.rename(columns={"scenario_id": "scenario"})
        columns = set(dataframe.columns)

    if normalized_format == "auto":
        normalized_format = (
            "long" if {"scenario", "belief_set", "probability"} <= columns else "wide"
        )

    if normalized_format == "long":
        required = {"scenario", "belief_set", "probability"}
        missing = sorted(required - set(dataframe.columns))
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Long ambiguity probability table is missing: {missing_text}")
        long = dataframe.loc[:, ["scenario", "belief_set", "probability"]].copy()
    else:
        if "scenario" not in dataframe.columns:
            raise ValueError(
                "Wide ambiguity probability table must include scenario or scenario_id",
            )
        inferred_belief_sets = tuple(
            column
            for column in dataframe.columns
            if column not in KNOWN_WIDE_METADATA_COLUMNS
        )
        selected_belief_sets = belief_sets or inferred_belief_sets
        if not selected_belief_sets:
            raise ValueError("No belief-set probability columns found")
        missing = [column for column in selected_belief_sets if column not in dataframe.columns]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                f"Configured belief sets are missing from probability table: {missing_text}",
            )
        long = dataframe.melt(
            id_vars=["scenario"],
            value_vars=list(selected_belief_sets),
            var_name="belief_set",
            value_name="probability",
        )

    long["scenario"] = long["scenario"].fillna("").astype(str).str.strip()
    long["belief_set"] = long["belief_set"].fillna("").astype(str).str.strip()
    long = long.loc[(long["scenario"] != "") & (long["belief_set"] != "")].copy()
    if long.empty:
        raise ValueError("No usable scenario/belief-set probabilities found")

    if belief_sets:
        allowed = set(belief_sets)
        long = long.loc[long["belief_set"].isin(allowed)].copy()
        missing = sorted(allowed - set(long["belief_set"]))
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Configured belief sets have no probabilities: {missing_text}")

    long["probability"] = pd.to_numeric(long["probability"], errors="coerce")
    validate_belief_sets(long, tolerance=tolerance)
    return long.reset_index(drop=True)


def validate_belief_sets(probabilities: pd.DataFrame, *, tolerance: float = 1e-8) -> None:
    if probabilities["probability"].isna().any():
        raise ValueError("Belief-set probabilities must be numeric")
    invalid_range = probabilities.loc[
        (probabilities["probability"] < -tolerance)
        | (probabilities["probability"] > 1.0 + tolerance)
    ]
    if not invalid_range.empty:
        raise ValueError("Belief-set probabilities must be between 0 and 1")

    duplicate_rows = probabilities.duplicated(subset=["scenario", "belief_set"], keep=False)
    if duplicate_rows.any():
        raise ValueError("Duplicate scenario/belief_set probability rows found")

    scenarios_by_belief = {
        belief_set: set(group["scenario"])
        for belief_set, group in probabilities.groupby("belief_set", dropna=False)
    }
    if not scenarios_by_belief:
        raise ValueError("No belief sets found")
    reference = next(iter(scenarios_by_belief.values()))
    for belief_set, scenarios in scenarios_by_belief.items():
        if scenarios != reference:
            raise ValueError(
                "Belief sets must assign probabilities to the same scenario space; "
                f"{belief_set} differs",
            )

    sums = probabilities.groupby("belief_set")["probability"].sum()
    bad_sums = sums.loc[(sums - 1.0).abs() > tolerance]
    if not bad_sums.empty:
        belief_text = ", ".join(f"{name}={value:.12g}" for name, value in bad_sums.items())
        raise ValueError(f"Belief-set probabilities must sum to 1: {belief_text}")


def construct_probability_bounds(
    probabilities: pd.DataFrame,
    *,
    tolerance: float = 1e-8,
) -> ProbabilityBounds:
    rows: list[dict[str, object]] = []
    for scenario, group in probabilities.groupby("scenario", sort=False):
        min_index = group["probability"].idxmin()
        max_index = group["probability"].idxmax()
        rows.append(
            {
                "scenario": str(scenario),
                "p_lower": float(probabilities.loc[min_index, "probability"]),
                "p_upper": float(probabilities.loc[max_index, "probability"]),
                "min_belief_set": str(probabilities.loc[min_index, "belief_set"]),
                "max_belief_set": str(probabilities.loc[max_index, "belief_set"]),
            },
        )
    bounds = ProbabilityBounds(
        scenarios=tuple(str(row["scenario"]) for row in rows),
        lower={str(row["scenario"]): float(row["p_lower"]) for row in rows},
        upper={str(row["scenario"]): float(row["p_upper"]) for row in rows},
        min_belief_set={str(row["scenario"]): str(row["min_belief_set"]) for row in rows},
        max_belief_set={str(row["scenario"]): str(row["max_belief_set"]) for row in rows},
    )
    validate_probability_bounds(bounds, tolerance=tolerance)
    return bounds


def mean_probability_vector(probabilities: pd.DataFrame) -> dict[str, float]:
    mean_values = probabilities.groupby("scenario", sort=False)["probability"].mean()
    total = float(mean_values.sum())
    if total <= 0.0:
        raise ValueError("Mean belief-set probability vector must sum to a positive value")
    return {str(scenario): float(value) / total for scenario, value in mean_values.items()}


def belief_set_probability_vector(probabilities: pd.DataFrame, belief_set: str) -> dict[str, float]:
    requested = str(belief_set).strip()
    rows = probabilities.loc[probabilities["belief_set"].eq(requested)]
    if rows.empty:
        raise ValueError(f"Belief set '{requested}' was not found in the probability table")
    return {
        str(row["scenario"]): float(row["probability"])
        for _, row in rows.iterrows()
    }


def validate_probability_bounds(bounds: ProbabilityBounds, *, tolerance: float = 1e-8) -> None:
    lower_total = sum(bounds.lower.values())
    upper_total = sum(bounds.upper.values())
    if lower_total > 1.0 + tolerance:
        raise ValueError("Probability lower bounds sum to more than 1")
    if upper_total < 1.0 - tolerance:
        raise ValueError("Probability upper bounds sum to less than 1")
    for scenario in bounds.scenarios:
        lower = bounds.lower[scenario]
        upper = bounds.upper[scenario]
        if lower < -tolerance or upper > 1.0 + tolerance or lower > upper + tolerance:
            raise ValueError(f"Invalid probability bounds for scenario {scenario}")


def npv_to_loss(npv: float) -> float:
    return -float(npv)


def solve_worst_case_mean_loss(
    losses: dict[str, float],
    bounds: ProbabilityBounds,
    *,
    tolerance: float = 1e-8,
) -> RobustMetricResult:
    _validate_loss_scenarios(losses, bounds)
    q = _adverse_probability_vector(losses, bounds, tolerance=tolerance)
    _validate_admissible_probabilities(q, bounds, tolerance=tolerance)
    robust_mean_loss = sum(q[scenario] * losses[scenario] for scenario in bounds.scenarios)
    return RobustMetricResult(
        robust_mean_loss=robust_mean_loss,
        robust_worst_npv=-robust_mean_loss,
        robust_tail_loss=None,
        robust_tail_npv=None,
        probabilities=q,
        tail_weights={scenario: 0.0 for scenario in bounds.scenarios},
    )


def solve_worst_case_expected_shortfall_loss(
    losses: dict[str, float],
    bounds: ProbabilityBounds,
    *,
    tail_alpha: float,
    tolerance: float = 1e-8,
) -> RobustMetricResult:
    _validate_loss_scenarios(losses, bounds)
    if not 0.0 < tail_alpha < 1.0:
        raise ValueError("ambiguity_aware_decision.tail_alpha must be in (0, 1)")
    beta = 1.0 - float(tail_alpha)
    q, tail_weights, tail_loss = _solve_worst_case_expected_shortfall_lp(
        losses,
        bounds,
        beta=beta,
        tolerance=tolerance,
    )
    _validate_admissible_probabilities(q, bounds, tolerance=tolerance)
    _validate_tail_weights(tail_weights, q, beta=beta, tolerance=tolerance)
    return RobustMetricResult(
        robust_mean_loss=None,
        robust_worst_npv=None,
        robust_tail_loss=tail_loss,
        robust_tail_npv=-tail_loss,
        probabilities=q,
        tail_weights=tail_weights,
    )


def score_ambiguity_aware_decisions(
    decision_results: pd.DataFrame,
    bounds: ProbabilityBounds,
    *,
    decision_mode: str,
    tail_alpha: float = 0.95,
    representative_probabilities: dict[str, float] | None = None,
    tolerance: float = 1e-8,
) -> AmbiguityScoreResult:
    if decision_results.empty:
        raise ValueError("Decision-result table is empty")
    scenario_column = _scenario_column(decision_results)
    required = {"decision_id", "technology_id", "npv", scenario_column}
    missing = sorted(required - set(decision_results.columns))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Decision-result table is missing required columns: {missing_text}")

    context_columns = [column for column in CONTEXT_COLUMNS if column in decision_results.columns]
    if not context_columns:
        context_columns = ["__decision_context"]
        decision_results = decision_results.copy()
        decision_results["__decision_context"] = "default"

    scores: list[dict[str, object]] = []
    selected_rows: list[dict[str, object]] = []
    probability_rows: list[dict[str, object]] = []
    excluded_rows: list[dict[str, object]] = []
    normalized_mode = str(decision_mode).strip()
    if normalized_mode not in ACTIVE_LOSS_LAW_DECISION_MODES:
        supported = ", ".join(ACTIVE_LOSS_LAW_DECISION_MODES)
        raise ValueError(f"Unsupported ambiguity decision mode '{decision_mode}'. Use: {supported}")

    groupby_key: str | list[str] = (
        context_columns[0] if len(context_columns) == 1 else context_columns
    )
    for context_key, context in decision_results.groupby(groupby_key, dropna=False):
        context_values = _context_values(context_columns, context_key)
        evaluated_scenarios = set(context[scenario_column].astype(str))
        expected_scenarios = set(bounds.scenarios)
        if evaluated_scenarios != expected_scenarios:
            missing_from_eval = sorted(expected_scenarios - evaluated_scenarios)
            extra_in_eval = sorted(evaluated_scenarios - expected_scenarios)
            raise ValueError(
                "Decision-result scenarios must match ambiguity probability scenarios exactly; "
                f"missing={missing_from_eval}, extra={extra_in_eval}",
            )

        # Regret is inherently cross-candidate (the best NPV any candidate reaches
        # in each scenario), so it is computed once per context, from every row
        # regardless of mode, the same way expected_npv/robust_worst_case_mean_npv
        # are always computed as diagnostics even when a different mode drives
        # the actual selection.
        context_npv = context.copy()
        context_npv["npv"] = pd.to_numeric(context_npv["npv"], errors="coerce")
        best_npv_by_scenario = context_npv.groupby(scenario_column)["npv"].max().to_dict()

        context_scores: list[dict[str, object]] = []
        candidates = context.groupby(["decision_id", "technology_id"], dropna=False)
        for (decision_id, technology_id), candidate in candidates:
            candidate_scenarios = set(candidate[scenario_column].astype(str))
            candidate_excluded = False
            for scenario in sorted(expected_scenarios - candidate_scenarios):
                excluded_rows.append(
                    _excluded_row(
                        context_values,
                        decision_id,
                        technology_id,
                        scenario,
                        "missing scenario NPV",
                    ),
                )
                candidate_excluded = True
            for scenario in sorted(candidate_scenarios - expected_scenarios):
                excluded_rows.append(
                    _excluded_row(
                        context_values,
                        decision_id,
                        technology_id,
                        scenario,
                        "scenario not present in probability bounds",
                    ),
                )
                candidate_excluded = True
            npv_series = pd.to_numeric(candidate["npv"], errors="coerce")
            if npv_series.isna().any():
                invalid_rows = candidate.loc[npv_series.isna()]
                for _, invalid_row in invalid_rows.iterrows():
                    scenario = str(invalid_row[scenario_column])
                    reason = str(invalid_row.get("infeasible_reason", "")).strip()
                    excluded_rows.append(
                        _excluded_row(
                            context_values,
                            decision_id,
                            technology_id,
                            scenario,
                            reason or "missing or non-numeric NPV",
                        ),
                    )
                candidate_excluded = True
            if candidate_excluded:
                continue

            npv_by_scenario = {
                str(row[scenario_column]): float(row["npv"]) for _, row in candidate.iterrows()
            }
            losses = {
                scenario: npv_to_loss(npv_by_scenario[scenario])
                for scenario in bounds.scenarios
            }
            mean_result = solve_worst_case_mean_loss(losses, bounds, tolerance=tolerance)
            tail_result = solve_worst_case_expected_shortfall_loss(
                losses,
                bounds,
                tail_alpha=tail_alpha,
                tolerance=tolerance,
            )
            expected_npv = _expected_npv(npv_by_scenario, bounds, representative_probabilities)
            max_regret = max(
                best_npv_by_scenario.get(scenario, float("nan")) - npv_by_scenario[scenario]
                for scenario in bounds.scenarios
            )
            if normalized_mode == "risk_neutral":
                robust_score = expected_npv
                probability_result = RobustMetricResult(
                    robust_mean_loss=None,
                    robust_worst_npv=None,
                    robust_tail_loss=None,
                    robust_tail_npv=None,
                    probabilities=_representative_probabilities(
                        bounds,
                        representative_probabilities,
                    ),
                    tail_weights={scenario: pd.NA for scenario in bounds.scenarios},
                )
            elif normalized_mode == "risk_averse_mean":
                robust_score = mean_result.robust_worst_npv
                probability_result = mean_result
            elif normalized_mode == "risk_averse_expected_shortfall":
                robust_score = tail_result.robust_tail_npv
                probability_result = tail_result
            elif normalized_mode == "minimax_regret":
                # Probability-free by construction (Savage's minimax regret): no
                # belief-set probability vector drives this choice, so both fields
                # are left unset rather than showing a representative vector that
                # did not actually influence the decision. Ranking is by highest
                # robust_score everywhere else in this function, so store the
                # negated regret (lower regret => higher score) instead of
                # special-casing an ascending sort just for this mode.
                robust_score = -max_regret
                probability_result = RobustMetricResult(
                    robust_mean_loss=None,
                    robust_worst_npv=None,
                    robust_tail_loss=None,
                    robust_tail_npv=None,
                    probabilities={scenario: pd.NA for scenario in bounds.scenarios},
                    tail_weights={scenario: pd.NA for scenario in bounds.scenarios},
                )
            row = {
                **_output_context(context_values),
                "decision_id": decision_id,
                "technology_id": technology_id,
                "decision_mode": normalized_mode,
                "expected_npv": expected_npv,
                "robust_mean_loss": mean_result.robust_mean_loss,
                "robust_worst_case_mean_npv": mean_result.robust_worst_npv,
                "robust_es_loss": tail_result.robust_tail_loss,
                "robust_expected_shortfall_npv": tail_result.robust_tail_npv,
                "max_regret": max_regret,
                # Backward-compatible aliases for older dashboards/tests.
                "robust_worst_npv": mean_result.robust_worst_npv,
                "robust_tail_loss": tail_result.robust_tail_loss,
                "robust_tail_npv": tail_result.robust_tail_npv,
                "robust_score": robust_score,
            }
            context_scores.append(row)
            for scenario in bounds.scenarios:
                probability_rows.append(
                    {
                        **_output_context(context_values),
                        "decision_id": decision_id,
                        "technology_id": technology_id,
                        "decision_mode": normalized_mode,
                        "scenario": scenario,
                        "probability": probability_result.probabilities[scenario],
                        "tail_weight": probability_result.tail_weights.get(scenario, 0.0),
                    },
                )

        if not context_scores:
            excluded_frame = pd.DataFrame(excluded_rows)
            raise AmbiguityRobustNoValidCandidatesError(
                "No valid ambiguity-aware robust candidates remain after excluding incomplete "
                "or infeasible candidates",
                excluded_frame,
            )
        context_scores.sort(
            key=lambda row: (
                float(row["robust_score"]),
                float(row["expected_npv"]),
                str(row["technology_id"]),
            ),
            reverse=True,
        )
        for rank, row in enumerate(context_scores, start=1):
            row["rank"] = rank
            row["selected"] = rank == 1
            scores.append(row)
        best = context_scores[0]
        selected_rows.append(
            {
                **_output_context(context_values),
                "selected_decision_id": best["decision_id"],
                "selected_technology_id": best["technology_id"],
                "selected_decision_year": best.get("decision_year", pd.NA),
                "selected_decision_mode": normalized_mode,
                "selected_score": best["robust_score"],
                "selected_expected_npv": best["expected_npv"],
                "selected_robust_worst_case_mean_npv": best[
                    "robust_worst_case_mean_npv"
                ],
                "selected_robust_expected_shortfall_npv": best[
                    "robust_expected_shortfall_npv"
                ],
                "selected_max_regret": best["max_regret"],
                # Backward-compatible aliases.
                "selected_risk_metric": normalized_mode,
                "selected_robust_worst_npv": best["robust_worst_case_mean_npv"],
                "selected_robust_tail_npv": best["robust_expected_shortfall_npv"],
            },
        )

    return AmbiguityScoreResult(
        scores=pd.DataFrame(scores),
        selected=pd.DataFrame(selected_rows),
        worst_case_probabilities=pd.DataFrame(probability_rows),
        excluded_candidates=pd.DataFrame(excluded_rows),
    )


def select_ambiguity_aware_decision(score_result: AmbiguityScoreResult) -> pd.Series:
    selected = score_result.scores.loc[score_result.scores["selected"].eq(True)]
    if selected.empty:
        raise ValueError("No selected ambiguity-aware decision found")
    return selected.iloc[0]


def _adverse_probability_vector(
    losses: dict[str, float],
    bounds: ProbabilityBounds,
    *,
    tolerance: float,
) -> dict[str, float]:
    q = {scenario: float(bounds.lower[scenario]) for scenario in bounds.scenarios}
    remaining = 1.0 - sum(q.values())
    if remaining < -tolerance:
        raise ValueError("Probability lower bounds sum to more than 1")
    for scenario in sorted(bounds.scenarios, key=lambda item: losses[item], reverse=True):
        room = max(float(bounds.upper[scenario]) - q[scenario], 0.0)
        take = min(room, max(remaining, 0.0))
        q[scenario] += take
        remaining -= take
        if remaining <= tolerance:
            break
    if abs(sum(q.values()) - 1.0) > max(tolerance, 1e-12):
        raise ValueError("Could not construct feasible worst-case probability vector")
    return _clean_probability_vector(q)


def _solve_worst_case_expected_shortfall_lp(
    losses: dict[str, float],
    bounds: ProbabilityBounds,
    *,
    beta: float,
    tolerance: float,
) -> tuple[dict[str, float], dict[str, float], float]:
    """Jointly solve for the adverse probability vector and CVaR tail-weights.

    Worst-case expected shortfall (CVaR_beta) is itself defined as a max over
    tail-weight vectors w for a *fixed* probability vector q. Optimizing over
    q as well turns this into one linear program in (q, w) rather than reusing
    the probability vector that maximizes worst-case *mean* loss and hoping it
    is also ES-optimal:

        maximize   w . loss
        subject to q in [lower, upper], sum(q) = 1
                   w >= 0, sum(w) = 1
                   beta * w <= q   (elementwise)

    The last constraint is CVaR's dual feasibility condition: a scenario can
    only receive tail weight in proportion to how much probability mass q
    actually places on it.
    """
    scenarios = list(bounds.scenarios)
    scenario_count = len(scenarios)
    loss_values = np.array([losses[scenario] for scenario in scenarios], dtype=float)
    lower_bounds = np.array([bounds.lower[scenario] for scenario in scenarios], dtype=float)
    upper_bounds = np.array([bounds.upper[scenario] for scenario in scenarios], dtype=float)

    # linprog minimizes, so minimize -(w . loss) to maximize w . loss. q carries no cost.
    objective = np.concatenate([np.zeros(scenario_count), -loss_values])

    equality_matrix = np.zeros((2, 2 * scenario_count))
    equality_matrix[0, :scenario_count] = 1.0  # sum(q) == 1
    equality_matrix[1, scenario_count:] = 1.0  # sum(w) == 1
    equality_rhs = np.array([1.0, 1.0])

    # beta * w_i - q_i <= 0  <=>  beta * w_i <= q_i
    inequality_matrix = np.zeros((scenario_count, 2 * scenario_count))
    for index in range(scenario_count):
        inequality_matrix[index, index] = -1.0
        inequality_matrix[index, scenario_count + index] = beta
    inequality_rhs = np.zeros(scenario_count)

    variable_bounds = [
        (float(lower_bounds[index]), float(upper_bounds[index]))
        for index in range(scenario_count)
    ]
    variable_bounds.extend((0.0, 1.0) for _ in range(scenario_count))

    result = linprog(
        c=objective,
        A_ub=inequality_matrix,
        b_ub=inequality_rhs,
        A_eq=equality_matrix,
        b_eq=equality_rhs,
        bounds=variable_bounds,
        method="highs",
    )
    if not result.success:
        raise ValueError(f"Robust expected-shortfall optimization failed: {result.message}")

    q_values = result.x[:scenario_count]
    tail_weight_values = result.x[scenario_count:]
    tail_loss = float(np.dot(tail_weight_values, loss_values))
    q = _clean_probability_vector(
        {scenario: float(q_values[index]) for index, scenario in enumerate(scenarios)},
    )
    tail_weights = _clean_probability_vector(
        {scenario: float(tail_weight_values[index]) for index, scenario in enumerate(scenarios)},
    )
    del tolerance
    return q, tail_weights, tail_loss


def _validate_loss_scenarios(losses: dict[str, float], bounds: ProbabilityBounds) -> None:
    if set(losses) != set(bounds.scenarios):
        missing = sorted(set(bounds.scenarios) - set(losses))
        extra = sorted(set(losses) - set(bounds.scenarios))
        raise ValueError(
            f"Loss scenarios must match probability bounds; missing={missing}, extra={extra}",
        )


def _clean_probability_vector(values: dict[str, float]) -> dict[str, float]:
    return {key: 0.0 if abs(value) < 1e-14 else float(value) for key, value in values.items()}


def _validate_admissible_probabilities(
    probabilities: dict[str, float],
    bounds: ProbabilityBounds,
    *,
    tolerance: float,
) -> None:
    if abs(sum(probabilities.values()) - 1.0) > max(tolerance, 1e-12):
        raise ValueError("Worst-case probability vector must sum to 1")
    for scenario in bounds.scenarios:
        probability = probabilities[scenario]
        if probability < bounds.lower[scenario] - tolerance:
            raise ValueError("Worst-case probability vector violates lower bounds")
        if probability > bounds.upper[scenario] + tolerance:
            raise ValueError("Worst-case probability vector violates upper bounds")


def _validate_tail_weights(
    tail_weights: dict[str, float],
    probabilities: dict[str, float],
    *,
    beta: float,
    tolerance: float,
) -> None:
    if abs(sum(tail_weights.values()) - 1.0) > max(tolerance, 1e-12):
        raise ValueError("Expected-shortfall tail weights must sum to 1")
    for scenario, tail_weight in tail_weights.items():
        if tail_weight < -tolerance:
            raise ValueError("Expected-shortfall tail weights must be non-negative")
        if beta * tail_weight > probabilities[scenario] + max(tolerance, 1e-12):
            raise ValueError("Expected-shortfall tail weights are infeasible")


def _scenario_column(dataframe: pd.DataFrame) -> str:
    if "scenario" in dataframe.columns:
        return "scenario"
    if "scenario_id" in dataframe.columns:
        return "scenario_id"
    raise ValueError("Decision-result table must include scenario or scenario_id")


def _context_values(columns: list[str], key: Any) -> dict[str, object]:
    if len(columns) == 1:
        return {columns[0]: key}
    key_tuple = key if isinstance(key, tuple) else (key,)
    return dict(zip(columns, key_tuple, strict=False))


def _output_context(values: dict[str, object]) -> dict[str, object]:
    return {column: values.get(column, pd.NA) for column in OUTPUT_CONTEXT_COLUMNS}


def _excluded_row(
    context_values: dict[str, object],
    decision_id: object,
    technology_id: object,
    scenario: str,
    reason: str,
) -> dict[str, object]:
    return {
        **_output_context(context_values),
        "decision_id": decision_id,
        "technology_id": technology_id,
        "missing_or_infeasible_scenario": scenario,
        "reason": reason,
    }


def _expected_npv(
    npv_by_scenario: dict[str, float],
    bounds: ProbabilityBounds,
    nominal_probabilities: dict[str, float] | None,
) -> float:
    if nominal_probabilities and set(nominal_probabilities) == set(bounds.scenarios):
        probabilities = nominal_probabilities
    else:
        midpoint = {
            scenario: (bounds.lower[scenario] + bounds.upper[scenario]) / 2.0
            for scenario in bounds.scenarios
        }
        total = sum(midpoint.values()) or 1.0
        probabilities = {scenario: value / total for scenario, value in midpoint.items()}
    return sum(probabilities[scenario] * npv_by_scenario[scenario] for scenario in bounds.scenarios)


def _representative_probabilities(
    bounds: ProbabilityBounds,
    representative_probabilities: dict[str, float] | None,
) -> dict[str, float]:
    if representative_probabilities and set(representative_probabilities) == set(bounds.scenarios):
        return {
            scenario: float(representative_probabilities[scenario])
            for scenario in bounds.scenarios
        }
    midpoint = {
        scenario: (bounds.lower[scenario] + bounds.upper[scenario]) / 2.0
        for scenario in bounds.scenarios
    }
    total = sum(midpoint.values()) or 1.0
    return {scenario: value / total for scenario, value in midpoint.items()}
