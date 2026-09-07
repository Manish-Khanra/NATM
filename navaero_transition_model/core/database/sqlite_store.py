from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


class SQLiteSimulationStore:
    def __init__(self, database_path: str | Path) -> None:
        self.requested_database_path = Path(database_path)
        self.database_path = self.requested_database_path

    def _cleanup_stale_sidecars(self, database_path: Path) -> None:
        if database_path.exists() and database_path.stat().st_size > 0:
            return
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(f"{database_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()

    def _fallback_database_path(self) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.requested_database_path.with_name(
            f"{self.requested_database_path.stem}_{timestamp}{self.requested_database_path.suffix}",
        )

    def _connect_path(self, database_path: Path) -> sqlite3.Connection:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_sidecars(database_path)
        connection = sqlite3.connect(database_path)
        # Some synced/workspace filesystems reject SQLite's default rollback
        # journal file writes. Memory journaling keeps the DB persistent while
        # avoiding that extra on-disk journal file.
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA synchronous=NORMAL")
        self.database_path = database_path
        return connection

    def _connect(self) -> sqlite3.Connection:
        try:
            return self._connect_path(self.requested_database_path)
        except (PermissionError, sqlite3.OperationalError):
            fallback_path = self._fallback_database_path()
            return self._connect_path(fallback_path)

    @staticmethod
    def _quote_identifier(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    @staticmethod
    def _sql_type(series: pd.Series) -> str:
        """The column type pandas' own sqlite writer would declare for `series`.

        Keeps a widened column indistinguishable from one created by the
        original `to_sql`, rather than leaving it typeless (which SQLite
        gives no affinity at all).
        """
        dtype = series.dtype
        if pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_integer_dtype(dtype):
            return "INTEGER"
        if pd.api.types.is_float_dtype(dtype):
            return "REAL"
        if pd.api.types.is_datetime64_any_dtype(dtype):
            return "TIMESTAMP"
        return "TEXT"

    def _ensure_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        frame: pd.DataFrame,
    ) -> None:
        """Widens an existing on-disk table to cover every column in `frame`.

        Runs accumulate into the same database over time via
        `if_exists="append"` (e.g. repeated `risk-attitudes-comparison`
        runs); if a later run's DataFrame gains a column an earlier run's
        on-disk table doesn't have, appending fails with `no column named
        ...` rather than writing the row. Adding the missing column first
        (existing rows simply read NULL for it) keeps append-based
        accumulation working across schema changes, without touching
        `if_exists="append"`'s intentional multi-run behavior.
        """
        quoted_table = self._quote_identifier(table_name)
        existing = {
            row[1] for row in connection.execute(f"PRAGMA table_info({quoted_table})")
        }
        if not existing:
            return  # Table doesn't exist yet; to_sql below creates it with a matching schema.
        for column in frame.columns:
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE {quoted_table} "
                    f"ADD COLUMN {self._quote_identifier(str(column))} "
                    f"{self._sql_type(frame[column])}",
                )

    def write_run(self, model, scenario) -> str:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        with self._connect() as connection:
            self._write_run_metadata(connection, run_id, scenario)
            self._write_input_tables(connection, run_id, model)
            self._write_output_tables(connection, run_id, model)
        return run_id

    def _write_run_metadata(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        scenario,
    ) -> None:
        metadata = pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "scenario_name": scenario.name,
                    "start_year": scenario.start_year,
                    "end_year": scenario.end_year,
                    "enabled_sectors": ",".join(scenario.enabled_sectors),
                    "created_utc": datetime.now(UTC).isoformat(),
                },
            ],
        )
        self._ensure_columns(connection, "runs", metadata)
        metadata.to_sql("runs", connection, if_exists="append", index=False)

    def _write_input_tables(self, connection: sqlite3.Connection, run_id: str, model) -> None:
        input_tables: dict[str, pd.DataFrame] = {}

        passenger_inputs = getattr(model, "aviation_passenger_inputs", None)
        if passenger_inputs is not None:
            input_tables.update(
                {
                    "input_aviation_fleet": passenger_inputs.fleet,
                    "input_aviation_passenger_fleet": passenger_inputs.fleet,
                    "input_aviation_technology_catalog": (
                        passenger_inputs.technology_catalog.to_frame()
                    ),
                    "input_aviation_passenger_technology_catalog": (
                        passenger_inputs.technology_catalog.to_frame()
                    ),
                    "input_aviation_scenario": passenger_inputs.scenario_wide,
                    "input_aviation_passenger_scenario": passenger_inputs.scenario_wide,
                },
            )

        cargo_inputs = getattr(model, "aviation_cargo_inputs", None)
        if cargo_inputs is not None:
            input_tables.update(
                {
                    "input_aviation_cargo_fleet": cargo_inputs.fleet,
                    "input_aviation_cargo_technology_catalog": (
                        cargo_inputs.technology_catalog.to_frame()
                    ),
                    "input_aviation_cargo_scenario": cargo_inputs.scenario_wide,
                },
            )

        maritime_cargo_inputs = getattr(model, "maritime_cargo_inputs", None)
        if maritime_cargo_inputs is not None:
            input_tables.update(
                {
                    "input_maritime_cargo_fleet": maritime_cargo_inputs.fleet,
                    "input_maritime_cargo_technology_catalog": (
                        maritime_cargo_inputs.technology_catalog.to_frame()
                    ),
                    "input_maritime_cargo_scenario": maritime_cargo_inputs.scenario_wide,
                },
            )

        maritime_passenger_inputs = getattr(model, "maritime_passenger_inputs", None)
        if maritime_passenger_inputs is not None:
            input_tables.update(
                {
                    "input_maritime_passenger_fleet": maritime_passenger_inputs.fleet,
                    "input_maritime_passenger_technology_catalog": (
                        maritime_passenger_inputs.technology_catalog.to_frame()
                    ),
                    "input_maritime_passenger_scenario": maritime_passenger_inputs.scenario_wide,
                },
            )

        if not input_tables:
            return
        for table_name, dataframe in input_tables.items():
            frame = dataframe.copy()
            frame.insert(0, "run_id", run_id)
            self._ensure_columns(connection, table_name, frame)
            frame.to_sql(table_name, connection, if_exists="append", index=False)

    def _write_output_tables(self, connection: sqlite3.Connection, run_id: str, model) -> None:
        output_tables = {
            "output_model_summary": model.to_frame(),
            "output_agents": model.to_agent_frame(),
            "output_aircraft": model.to_aircraft_frame(),
            "output_aviation_technology": model.to_aviation_technology_frame(),
            "output_aviation_energy_emissions": model.to_aviation_energy_emissions_frame(),
            "output_aviation_investments": model.to_aviation_investment_frame(),
            "output_aviation_robust_frontier": model.to_aviation_robust_frontier_frame(),
            "output_maritime_technology": model.to_maritime_technology_frame(),
            "output_maritime_energy_emissions": model.to_maritime_energy_emissions_frame(),
            "output_maritime_investments": model.to_maritime_investment_frame(),
            "output_maritime_robust_frontier": model.to_maritime_robust_frontier_frame(),
            "output_ambiguity_probability_bounds": (model.to_ambiguity_probability_bounds_frame()),
            "output_ambiguity_decision_scores": model.to_ambiguity_decision_scores_frame(),
            "output_ambiguity_worst_case_probabilities": (
                model.to_ambiguity_worst_case_probabilities_frame()
            ),
            "output_selected_ambiguity_aware_decisions": (
                model.to_selected_ambiguity_decisions_frame()
            ),
            "output_ambiguity_excluded_candidates": (
                model.to_ambiguity_excluded_candidates_frame()
            ),
        }
        for table_name, dataframe in output_tables.items():
            if dataframe.empty:
                continue
            frame = dataframe.copy()
            frame.insert(0, "run_id", run_id)
            self._ensure_columns(connection, table_name, frame)
            frame.to_sql(table_name, connection, if_exists="append", index=False)
