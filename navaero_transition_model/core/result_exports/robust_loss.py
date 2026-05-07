from __future__ import annotations

import pandas as pd

LOSS_SUMMARY_COLUMNS = (
    "candidate_technology",
    "selected_flag",
    "expected_operating_cost_regret_eur",
    "tail_operating_cost_regret_eur",
    "expected_npv_loss_eur",
    "tail_npv_loss_eur",
)


def robust_frontier_loss_summary(
    frontier: pd.DataFrame,
    *,
    tail_alpha: float = 0.25,
) -> pd.DataFrame:
    """Summarise monetary downside diagnostics from robust frontier rows.

    Regret/loss is diagnostic only. It does not affect investment selection,
    which remains governed by the robust utility score.
    """
    required = {
        "candidate_technology",
        "scenario_id",
        "scenario_probability",
        "candidate_operating_cost",
    }
    if frontier.empty or not required.issubset(frontier.columns):
        return pd.DataFrame(columns=LOSS_SUMMARY_COLUMNS)

    frame = frontier.copy()
    numeric_columns = [
        "scenario_probability",
        "candidate_operating_cost",
        "candidate_npv",
        "expected_shortfall_alpha",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["scenario_probability"] = frame["scenario_probability"].fillna(0.0)
    frame["candidate_operating_cost"] = frame["candidate_operating_cost"].fillna(0.0)
    if "selected_flag" in frame.columns:
        frame["selected_flag"] = (
            frame["selected_flag"].astype(str).str.lower().isin({"true", "1", "yes"})
        )
    else:
        frame["selected_flag"] = False

    alpha = _tail_alpha(frame, tail_alpha)
    decision_columns = _decision_columns(frame)
    scenario_group = [*decision_columns, "scenario_id"]
    frame["operating_cost_regret_eur"] = frame["candidate_operating_cost"] - frame.groupby(
        scenario_group,
        dropna=False,
    )["candidate_operating_cost"].transform("min")

    has_npv = "candidate_npv" in frame.columns and frame["candidate_npv"].notna().any()
    if has_npv:
        frame["npv_loss_eur"] = frame.groupby(
            scenario_group,
            dropna=False,
        )["candidate_npv"].transform("max") - frame["candidate_npv"]

    decision_candidate_columns = [*decision_columns, "candidate_technology"]
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(decision_candidate_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        candidate_technology = str(keys[-1])
        row: dict[str, object] = {
            "candidate_technology": candidate_technology,
            "selected_flag": bool(group["selected_flag"].max()),
            "expected_operating_cost_regret_eur": _expected_loss(
                group,
                "operating_cost_regret_eur",
            ),
            "tail_operating_cost_regret_eur": _tail_loss(
                group,
                "operating_cost_regret_eur",
                alpha,
            ),
            "expected_npv_loss_eur": None,
            "tail_npv_loss_eur": None,
        }
        if has_npv:
            row["expected_npv_loss_eur"] = _expected_loss(group, "npv_loss_eur")
            row["tail_npv_loss_eur"] = _tail_loss(group, "npv_loss_eur", alpha)
        rows.append(row)

    summary = pd.DataFrame(rows)
    if summary.empty:
        return pd.DataFrame(columns=LOSS_SUMMARY_COLUMNS)
    summary = (
        summary.groupby("candidate_technology", as_index=False)
        .agg(
            selected_flag=("selected_flag", "max"),
            expected_operating_cost_regret_eur=("expected_operating_cost_regret_eur", "mean"),
            tail_operating_cost_regret_eur=("tail_operating_cost_regret_eur", "mean"),
            expected_npv_loss_eur=("expected_npv_loss_eur", "mean"),
            tail_npv_loss_eur=("tail_npv_loss_eur", "mean"),
        )
        .sort_values("tail_operating_cost_regret_eur", ascending=False)
    )
    return summary.loc[:, list(LOSS_SUMMARY_COLUMNS)]


def _tail_alpha(frame: pd.DataFrame, fallback: float) -> float:
    if "expected_shortfall_alpha" in frame.columns:
        values = frame["expected_shortfall_alpha"].dropna()
        if not values.empty:
            return max(min(float(values.iloc[0]), 1.0), 1e-9)
    return max(min(float(fallback), 1.0), 1e-9)


def _decision_columns(frame: pd.DataFrame) -> list[str]:
    candidates = (
        "year",
        "operator_name",
        "asset_id",
        "aircraft_id",
        "vessel_id",
        "segment",
        "decision_attitude",
    )
    return [column for column in candidates if column in frame.columns]


def _expected_loss(group: pd.DataFrame, column: str) -> float:
    valid = group.dropna(subset=[column]).copy()
    if valid.empty:
        return 0.0
    probability_sum = float(valid["scenario_probability"].sum())
    if probability_sum <= 0.0:
        return float(valid[column].mean())
    return float((valid[column] * valid["scenario_probability"]).sum() / probability_sum)


def _tail_loss(group: pd.DataFrame, column: str, alpha: float) -> float:
    valid = group.dropna(subset=[column]).sort_values(column, ascending=False)
    if valid.empty:
        return 0.0
    probability_sum = float(valid["scenario_probability"].sum())
    if probability_sum <= 0.0:
        return float(valid[column].max())

    remaining_tail = min(max(alpha, 1e-9), probability_sum)
    weighted_sum = 0.0
    consumed = 0.0
    for row in valid.itertuples(index=False):
        probability = max(float(row.scenario_probability), 0.0)
        take = min(probability, remaining_tail - consumed)
        if take <= 0.0:
            break
        weighted_sum += take * float(getattr(row, column))
        consumed += take
    if consumed <= 0.0:
        return 0.0
    return weighted_sum / consumed
