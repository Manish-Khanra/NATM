from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_SCENARIO_ID = "baseline"
SCENARIO_ID_COLUMN = "scenario_id"
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
        if SCENARIO_ID_COLUMN not in normalized.columns:
            normalized[SCENARIO_ID_COLUMN] = DEFAULT_SCENARIO_ID
        for column in normalized.select_dtypes(include=["object", "string"]).columns:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        normalized[SCENARIO_ID_COLUMN] = normalized[SCENARIO_ID_COLUMN].replace(
            "", DEFAULT_SCENARIO_ID
        )
        year_columns = _scenario_year_columns(normalized)
        long_dataframe = normalized.melt(
            id_vars=[SCENARIO_ID_COLUMN, *SCENARIO_SCOPE_COLUMNS],
            value_vars=year_columns,
            var_name="year",
            value_name="value",
        )
        long_dataframe["year"] = long_dataframe["year"].astype(int)

        self._wide = normalized.reset_index(drop=True)
        self._long = long_dataframe.reset_index(drop=True)
        self._cache: dict[tuple[Any, ...], float | None] = {}
        # (scenario_id, variable_name, year) -> pre-filtered rows as plain
        # dicts. value() is called per candidate technology x scenario x
        # decision-year during an ambiguity-aware evaluation sweep, but the
        # boolean-mask filter over the full long table only actually depends
        # on this scope-independent triple, not on the per-aircraft scope
        # kwargs -- caching it here turns what would be millions of full
        # -table pandas filters (plus row.iterrows() overhead) into at most
        # one per distinct (scenario_id, variable_name, year) combination.
        self._rows_cache: dict[tuple[str, str, int], list[dict[str, str]]] = {}

    @classmethod
    def from_csv(cls, path: str | Path) -> ScenarioTable:
        return cls(_read_csv(path))

    def invalidate_cache(self) -> None:
        """Clear cached lookups after `_long` is mutated in place (e.g. in tests)."""
        self._cache.clear()
        self._rows_cache.clear()

    def to_wide_frame(self) -> pd.DataFrame:
        return self._wide.copy()

    def to_long_frame(self) -> pd.DataFrame:
        return self._long.copy()

    def matching_rows(
        self,
        variable_name: str,
        year: int,
        *,
        scenario_id: str | None = None,
        **scope: str,
    ) -> pd.DataFrame:
        requested_scenario = _clean_scope_value(scenario_id) or DEFAULT_SCENARIO_ID
        rows = self._matching_rows_for_scenario(
            requested_scenario,
            variable_name,
            year,
            scope,
        )
        if rows.empty and requested_scenario != DEFAULT_SCENARIO_ID:
            rows = self._matching_rows_for_scenario(
                DEFAULT_SCENARIO_ID,
                variable_name,
                year,
                scope,
            )

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

    def _matching_rows_for_scenario(
        self,
        scenario_id: str,
        variable_name: str,
        year: int,
        scope: dict[str, str],
    ) -> pd.DataFrame:
        rows = self._long.loc[
            (self._long["scenario_id"] == scenario_id)
            & (self._long["variable_name"] == variable_name)
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
                rows = rows.loc[(candidate_values == "") | (candidate_values == requested_text)]
        return rows.reset_index(drop=True)

    def has_rows(self, variable_name: str) -> bool:
        return not self._long.loc[self._long["variable_name"] == variable_name].empty

    def value(
        self,
        variable_name: str,
        year: int,
        *,
        scenario_id: str | None = None,
        default: float | None = None,
        **scope: str,
    ) -> float | None:
        requested_scenario = _clean_scope_value(scenario_id) or DEFAULT_SCENARIO_ID
        normalized_scope = tuple(
            sorted((key, _clean_scope_value(value)) for key, value in scope.items()),
        )
        cache_key = (requested_scenario, variable_name, year, normalized_scope, default)
        if cache_key in self._cache:
            return self._cache[cache_key]

        best_row = self._best_value_row_for_scenario(
            requested_scenario,
            variable_name,
            year,
            scope,
        )
        if best_row is None and requested_scenario != DEFAULT_SCENARIO_ID:
            best_row = self._best_value_row_for_scenario(
                DEFAULT_SCENARIO_ID,
                variable_name,
                year,
                scope,
            )
        if best_row is None:
            self._cache[cache_key] = default
            return default

        resolved = float(best_row["value"])
        self._cache[cache_key] = resolved
        return resolved

    def _rows_for(self, scenario_id: str, variable_name: str, year: int) -> list[dict[str, str]]:
        key = (scenario_id, variable_name, year)
        cached = self._rows_cache.get(key)
        if cached is not None:
            return cached
        rows = self._long.loc[
            (self._long["scenario_id"] == scenario_id)
            & (self._long["variable_name"] == variable_name)
            & (self._long["year"] == year),
        ]
        records = rows.to_dict("records")
        self._rows_cache[key] = records
        return records

    def _best_value_row_for_scenario(
        self,
        scenario_id: str,
        variable_name: str,
        year: int,
        scope: dict[str, str],
    ) -> dict[str, str] | None:
        rows = self._rows_for(scenario_id, variable_name, year)
        best_row: dict[str, str] | None = None
        best_score = -1
        for row in rows:
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
        return best_row
