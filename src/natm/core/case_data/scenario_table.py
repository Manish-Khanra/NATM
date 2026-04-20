from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

SCENARIO_SCOPE_COLUMNS = (
    "variable_group",
    "variable_name",
    "country",
    "operator_name",
    "segment",
    "technology_name",
    "primary_energy_carrier",
    "secondary_energy_carrier",
    "saf_pathway",
    "unit",
)


def _read_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    dataframe = pd.read_csv(csv_path)
    if dataframe.empty:
        raise ValueError(f"CSV file has no rows: {csv_path}")
    return dataframe


def _ensure_columns(
    dataframe: pd.DataFrame,
    required_columns: tuple[str, ...],
    label: str,
) -> None:
    missing = [column for column in required_columns if column not in dataframe.columns]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{label} is missing required columns: {missing_text}")


def _scenario_year_columns(dataframe: pd.DataFrame) -> list[str]:
    year_columns = [column for column in dataframe.columns if column.isdigit()]
    if not year_columns:
        raise ValueError("aviation scenario CSV must include at least one year column")
    return sorted(year_columns, key=int)


def _clean_scope_value(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


class ScenarioTable:
    def __init__(self, wide_dataframe: pd.DataFrame) -> None:
        _ensure_columns(wide_dataframe, SCENARIO_SCOPE_COLUMNS, "aviation scenario")
        normalized = wide_dataframe.copy()
        for column in normalized.select_dtypes(include=["object", "string"]).columns:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        year_columns = _scenario_year_columns(normalized)
        long_dataframe = normalized.melt(
            id_vars=list(SCENARIO_SCOPE_COLUMNS),
            value_vars=year_columns,
            var_name="year",
            value_name="value",
        )
        long_dataframe["year"] = long_dataframe["year"].astype(int)

        self._wide = normalized.reset_index(drop=True)
        self._long = long_dataframe.reset_index(drop=True)
        self._cache: dict[tuple[Any, ...], float | None] = {}

    @classmethod
    def from_csv(cls, path: str | Path) -> ScenarioTable:
        return cls(_read_csv(path))

    def to_wide_frame(self) -> pd.DataFrame:
        return self._wide.copy()

    def to_long_frame(self) -> pd.DataFrame:
        return self._long.copy()

    def matching_rows(
        self,
        variable_name: str,
        year: int,
        **scope: str,
    ) -> pd.DataFrame:
        rows = self._long.loc[
            (self._long["variable_name"] == variable_name)
            & (self._long["year"] == year),
        ].copy()
        if rows.empty:
            return rows.reset_index(drop=True)

        for column, requested_value in scope.items():
            requested_text = _clean_scope_value(requested_value)
            candidate_values = rows[column].map(_clean_scope_value)
            if requested_text == "":
                rows = rows.loc[candidate_values == ""]
            else:
                rows = rows.loc[
                    (candidate_values == "")
                    | (candidate_values == requested_text)
                ]

        if rows.empty:
            return rows.reset_index(drop=True)

        scored = rows.copy()
        scope_columns = [column for column in scope if column in scored.columns]
        if scope_columns:
            scored["_specificity"] = 0
            for column in scope_columns:
                scored["_specificity"] = scored["_specificity"] + (
                    scored[column].map(_clean_scope_value) != ""
                ).astype(int)
            scored = scored.sort_values(
                by=["_specificity"] + scope_columns,
                ascending=[False] + [True] * len(scope_columns),
                kind="stable",
            ).drop(columns="_specificity")
        return scored.reset_index(drop=True)

    def has_rows(self, variable_name: str) -> bool:
        return not self._long.loc[self._long["variable_name"] == variable_name].empty

    def value(
        self,
        variable_name: str,
        year: int,
        *,
        default: float | None = None,
        **scope: str,
    ) -> float | None:
        normalized_scope = tuple(
            sorted((key, _clean_scope_value(value)) for key, value in scope.items()),
        )
        cache_key = (variable_name, year, normalized_scope, default)
        if cache_key in self._cache:
            return self._cache[cache_key]

        rows = self._long.loc[
            (self._long["variable_name"] == variable_name)
            & (self._long["year"] == year),
        ]
        if rows.empty:
            self._cache[cache_key] = default
            return default

        best_row: pd.Series | None = None
        best_score = -1
        for _, row in rows.iterrows():
            score = 0
            matched = True
            for column, requested_value in scope.items():
                candidate_value = _clean_scope_value(row.get(column, ""))
                requested_text = _clean_scope_value(requested_value)
                if candidate_value == "":
                    continue
                if requested_text == "":
                    matched = False
                    break
                if candidate_value != requested_text:
                    matched = False
                    break
                score += 1

            if matched and score > best_score:
                best_row = row
                best_score = score

        if best_row is None:
            self._cache[cache_key] = default
            return default

        resolved = float(best_row["value"])
        self._cache[cache_key] = resolved
        return resolved
