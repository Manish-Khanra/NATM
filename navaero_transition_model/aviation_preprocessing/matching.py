from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import pandas as pd

from navaero_transition_model.aviation_preprocessing.common import (
    normalize_descriptor,
    normalize_operator_name,
    normalize_text,
)


def _similarity(left: object, right: object) -> float:
    left_text = normalize_text(left, lowercase=True)
    right_text = normalize_text(right, lowercase=True)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(a=left_text, b=right_text).ratio()


def _aircraft_type_similarity(stock_row: pd.Series, aircraft_row: pd.Series) -> float:
    aircraft_type = normalize_descriptor(stock_row.get("aircraft_type", ""))
    typecode = normalize_descriptor(aircraft_row.get("typecode", ""))
    model = normalize_descriptor(aircraft_row.get("model", ""))
    if not aircraft_type:
        return 0.0
    candidates = [text for text in (typecode, model) if text]
    if not candidates:
        return 0.0
    exact_containment = max(
        1.0
        if aircraft_type == candidate or aircraft_type in candidate or candidate in aircraft_type
        else 0.0
        for candidate in candidates
    )
    if exact_containment == 1.0:
        return 1.0
    return max(_similarity(aircraft_type, candidate) for candidate in candidates)


def _optional_exact_score(stock_value: object, aircraft_value: object) -> float:
    stock_text = normalize_text(stock_value, lowercase=True)
    aircraft_text = normalize_text(aircraft_value, lowercase=True)
    if not stock_text or not aircraft_text:
        return 0.0
    return 1.0 if stock_text == aircraft_text else 0.0


@dataclass
class AviationStockMatchResult:
    enriched_stock: pd.DataFrame
    matched_records: pd.DataFrame
    ambiguous_records: pd.DataFrame
    unmatched_records: pd.DataFrame
    report: pd.DataFrame


class AviationStockMatcher:
    def __init__(
        self,
        *,
        high_confidence_threshold: float = 0.82,
        ambiguous_threshold: float = 0.65,
        ambiguity_gap: float = 0.06,
    ) -> None:
        self.high_confidence_threshold = high_confidence_threshold
        self.ambiguous_threshold = ambiguous_threshold
        self.ambiguity_gap = ambiguity_gap

    def _exact_candidates(self, stock_row: pd.Series, aircraft_db: pd.DataFrame) -> pd.DataFrame:
        operator_name = normalize_operator_name(stock_row.get("operator_name", ""))
        build_year = stock_row.get("build_year", pd.NA)
        status = normalize_text(stock_row.get("status_normalized", stock_row.get("status", "")))

        operator_column = (
            "operator_normalized" if "operator_normalized" in aircraft_db.columns else "operator"
        )
        candidates = aircraft_db.loc[
            aircraft_db[operator_column].astype(str).map(normalize_operator_name).eq(operator_name),
        ].copy()
        if candidates.empty:
            return candidates

        type_match = candidates.apply(
            lambda aircraft: _aircraft_type_similarity(stock_row, aircraft) >= 0.999,
            axis=1,
        )
        candidates = candidates.loc[type_match]
        if pd.notna(build_year):
            candidates = candidates.loc[
                pd.to_numeric(candidates["built_year"], errors="coerce").eq(float(build_year)),
            ]
        if status:
            status_match = candidates["status"].astype(str).str.lower().str.strip().eq(status)
            if status_match.any():
                candidates = candidates.loc[status_match]
        return candidates.reset_index(drop=True)

    def _score_candidates(self, stock_row: pd.Series, aircraft_db: pd.DataFrame) -> pd.DataFrame:
        scored = aircraft_db.copy()
        if scored.empty:
            scored["match_score"] = pd.Series(dtype=float)
            return scored

        operator_name = normalize_operator_name(stock_row.get("operator_name", ""))
        build_year = pd.to_numeric(
            pd.Series([stock_row.get("build_year", pd.NA)]), errors="coerce"
        ).iloc[0]
        engine_count = pd.to_numeric(
            pd.Series([stock_row.get("engine_count", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        seat_total = pd.to_numeric(
            pd.Series([stock_row.get("seat_total", pd.NA)]),
            errors="coerce",
        ).iloc[0]
        status = normalize_text(stock_row.get("status_normalized", stock_row.get("status", "")))

        scores: list[float] = []
        for aircraft in scored.itertuples(index=False):
            aircraft_series = pd.Series(aircraft._asdict())
            score = 0.0
            score += 0.35 * _aircraft_type_similarity(stock_row, aircraft_series)
            score += 0.25 * _similarity(
                operator_name,
                aircraft_series.get(
                    "operator_normalized",
                    normalize_operator_name(aircraft_series.get("operator", "")),
                ),
            )

            candidate_year = pd.to_numeric(
                pd.Series([aircraft_series.get("built_year", pd.NA)]),
                errors="coerce",
            ).iloc[0]
            if pd.notna(build_year) and pd.notna(candidate_year):
                year_gap = abs(float(build_year) - float(candidate_year))
                if year_gap == 0:
                    score += 0.15
                elif year_gap <= 1:
                    score += 0.10
                elif year_gap <= 2:
                    score += 0.05

            if "engine_count" in aircraft_series.index and pd.notna(engine_count):
                candidate_engine_count = pd.to_numeric(
                    pd.Series([aircraft_series.get("engine_count", pd.NA)]),
                    errors="coerce",
                ).iloc[0]
                if pd.notna(candidate_engine_count) and float(candidate_engine_count) == float(
                    engine_count,
                ):
                    score += 0.08
            if "seat_total" in aircraft_series.index and pd.notna(seat_total):
                candidate_seat_total = pd.to_numeric(
                    pd.Series([aircraft_series.get("seat_total", pd.NA)]),
                    errors="coerce",
                ).iloc[0]
                if pd.notna(candidate_seat_total):
                    seat_gap = abs(float(candidate_seat_total) - float(seat_total))
                    if seat_gap == 0:
                        score += 0.08
                    elif seat_gap <= 5:
                        score += 0.05
            if status:
                score += 0.04 * _optional_exact_score(status, aircraft_series.get("status", ""))

            engine_manufacturer = stock_row.get("engine_manufacturer", "")
            if "engine_manufacturer" in aircraft_series.index:
                score += 0.03 * _similarity(
                    normalize_operator_name(engine_manufacturer),
                    aircraft_series.get("engine_manufacturer", ""),
                )
            engine_type = stock_row.get("engine_type", "")
            if "engine_type" in aircraft_series.index:
                score += 0.02 * _similarity(engine_type, aircraft_series.get("engine_type", ""))
            scores.append(min(score, 1.0))

        scored["match_score"] = scores
        return scored.sort_values(by="match_score", ascending=False, kind="stable").reset_index(
            drop=True,
        )

    def match(
        self, cleaned_stock: pd.DataFrame, aircraft_db: pd.DataFrame
    ) -> AviationStockMatchResult:
        stock = cleaned_stock.copy()
        db = aircraft_db.copy()
        for column in ("registration", "icao24", "serial_number"):
            if column not in stock.columns:
                stock[column] = pd.NA
        stock["match_confidence"] = pd.to_numeric(stock.get("match_confidence"), errors="coerce")
        stock["match_method"] = stock.get(
            "match_method", pd.Series(index=stock.index, dtype=object)
        )
        stock["match_status"] = "unmatched"

        exact_matches = 0
        high_confidence_matches = 0
        ambiguous_matches = 0
        unmatched_rows = 0

        for index, row in stock.iterrows():
            exact = self._exact_candidates(row, db)
            if len(exact) == 1:
                match = exact.iloc[0]
                stock.loc[index, "registration"] = match["registration"]
                stock.loc[index, "icao24"] = match["icao24"]
                stock.loc[index, "serial_number"] = match.get("serial_number", pd.NA)
                stock.loc[index, "is_german_flag"] = bool(match.get("is_german_flag", False))
                stock.loc[index, "match_confidence"] = 1.0
                stock.loc[index, "match_method"] = "exact_multi_feature"
                stock.loc[index, "match_status"] = "matched"
                exact_matches += 1
                continue
            if len(exact) > 1:
                stock.loc[index, "match_confidence"] = 0.5
                stock.loc[index, "match_method"] = "exact_ambiguous"
                stock.loc[index, "match_status"] = "ambiguous"
                ambiguous_matches += 1
                continue

            scored = self._score_candidates(row, db)
            if scored.empty:
                stock.loc[index, "match_confidence"] = 0.0
                stock.loc[index, "match_method"] = "unmatched"
                unmatched_rows += 1
                continue

            best = scored.iloc[0]
            second_score = float(scored.iloc[1]["match_score"]) if len(scored) > 1 else 0.0
            best_score = float(best["match_score"])
            score_gap = best_score - second_score

            if best_score >= self.high_confidence_threshold and score_gap >= self.ambiguity_gap:
                stock.loc[index, "registration"] = best["registration"]
                stock.loc[index, "icao24"] = best["icao24"]
                stock.loc[index, "serial_number"] = best.get("serial_number", pd.NA)
                stock.loc[index, "is_german_flag"] = bool(best.get("is_german_flag", False))
                stock.loc[index, "match_confidence"] = best_score
                stock.loc[index, "match_method"] = "scored_high_confidence"
                stock.loc[index, "match_status"] = "matched"
                high_confidence_matches += 1
            elif best_score >= self.ambiguous_threshold:
                stock.loc[index, "match_confidence"] = best_score
                stock.loc[index, "match_method"] = "scored_ambiguous"
                stock.loc[index, "match_status"] = "ambiguous"
                ambiguous_matches += 1
            else:
                stock.loc[index, "match_confidence"] = best_score
                stock.loc[index, "match_method"] = "unmatched"
                unmatched_rows += 1

        report = pd.DataFrame(
            [
                {"metric": "exact_matches", "value": exact_matches},
                {"metric": "high_confidence_matches", "value": high_confidence_matches},
                {"metric": "ambiguous_matches", "value": ambiguous_matches},
                {"metric": "unmatched_rows", "value": unmatched_rows},
                {"metric": "total_rows", "value": len(stock)},
            ],
        )

        matched_records = stock.loc[stock["match_status"] == "matched"].reset_index(drop=True)
        ambiguous_records = stock.loc[stock["match_status"] == "ambiguous"].reset_index(drop=True)
        unmatched_records = stock.loc[stock["match_status"] == "unmatched"].reset_index(drop=True)
        return AviationStockMatchResult(
            enriched_stock=stock.reset_index(drop=True),
            matched_records=matched_records,
            ambiguous_records=ambiguous_records,
            unmatched_records=unmatched_records,
            report=report,
        )
