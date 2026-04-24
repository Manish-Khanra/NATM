from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from navaero_transition_model.aviation_preprocessing.activity_profiles import (
    AviationActivityProfileBuilder,
)
from navaero_transition_model.aviation_preprocessing.allocation import AviationAllocationBuilder
from navaero_transition_model.aviation_preprocessing.baseline import AviationBaselineBuilder
from navaero_transition_model.aviation_preprocessing.calibration import AviationCalibrationBuilder
from navaero_transition_model.aviation_preprocessing.flightlists import (
    FlightlistIngestionConfig,
    OpenSkyFlightlistIngestor,
)
from navaero_transition_model.aviation_preprocessing.matching import AviationStockMatcher
from navaero_transition_model.aviation_preprocessing.opensky_aircraft_db import (
    OpenSkyAircraftDatabaseConfig,
    OpenSkyAircraftDatabaseProcessor,
)
from navaero_transition_model.aviation_preprocessing.stock_cleaner import AviationStockCleaner


@dataclass
class AviationPreprocessingPaths:
    raw_dir: Path = Path("data/raw/aviation")
    processed_dir: Path = Path("data/processed/aviation")


@dataclass
class AviationPreprocessingPipeline:
    paths: AviationPreprocessingPaths = field(default_factory=AviationPreprocessingPaths)

    def run_phase_1(
        self,
        *,
        stock_input_path: str | Path,
        opensky_config: OpenSkyAircraftDatabaseConfig | None = None,
        opensky_raw_path: str | Path | None = None,
    ) -> dict[str, Path]:
        cleaner = AviationStockCleaner()
        cleaned_stock = cleaner.clean(stock_input_path)
        cleaned_stock_path = self.paths.processed_dir / "aviation_fleet_stock_cleaned.csv"
        cleaned_stock_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_stock.to_csv(cleaned_stock_path, index=False)

        config = opensky_config or OpenSkyAircraftDatabaseConfig()
        config.raw_snapshot_dir = self.paths.raw_dir / "opensky_aircraft_db"
        config.processed_output_path = (
            self.paths.processed_dir / "opensky_aircraft_db_processed.csv"
        )
        processor = OpenSkyAircraftDatabaseProcessor(config)
        if opensky_raw_path is None:
            aircraft_db = processor.download_and_process()
        else:
            aircraft_db = processor.process(
                opensky_raw_path, output_path=config.processed_output_path
            )

        matcher = AviationStockMatcher()
        match_result = matcher.match(cleaned_stock, aircraft_db)
        enriched_path = self.paths.processed_dir / "aviation_fleet_stock_enriched.csv"
        report_path = self.paths.processed_dir / "aviation_stock_matching_report.csv"
        match_result.enriched_stock.to_csv(enriched_path, index=False)
        match_result.report.to_csv(report_path, index=False)
        return {
            "cleaned_stock": cleaned_stock_path,
            "opensky_aircraft_db_processed": self.paths.processed_dir
            / "opensky_aircraft_db_processed.csv",
            "enriched_stock": enriched_path,
            "matching_report": report_path,
        }

    def run_phase_2(
        self,
        *,
        flightlist_input_folder: str | Path,
        airport_metadata_path: str | Path,
        aircraft_db_processed_path: str | Path | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
    ) -> dict[str, Path]:
        ingestor = OpenSkyFlightlistIngestor(
            FlightlistIngestionConfig(
                input_folder=Path(flightlist_input_folder),
                output_parquet_path=self.paths.processed_dir
                / "opensky_flightlist_processed.parquet",
                airport_metadata_path=Path(airport_metadata_path),
                year_start=year_start,
                year_end=year_end,
            ),
        )
        ingestor.ingest()
        builder = AviationActivityProfileBuilder(airport_metadata_path=Path(airport_metadata_path))
        builder.build(
            processed_flightlist_path=self.paths.processed_dir
            / "opensky_flightlist_processed.parquet",
            aircraft_db_processed_path=aircraft_db_processed_path,
            output_dir=self.paths.processed_dir,
        )
        return {
            "flightlist_processed": self.paths.processed_dir
            / "opensky_flightlist_processed.parquet",
            "activity_by_type": self.paths.processed_dir / "aviation_activity_profiles_by_type.csv",
            "activity_by_operator_type": self.paths.processed_dir
            / "aviation_activity_profiles_by_operator_type.csv",
            "activity_by_airport_type": self.paths.processed_dir
            / "aviation_activity_profiles_by_airport_type.csv",
            "activity_by_registration": self.paths.processed_dir
            / "aviation_activity_profiles_by_registration.csv",
        }

    def run_phase_3(
        self,
        *,
        stock_input_path: str | Path,
        airport_metadata_path: str | Path,
        technology_catalog_path: str | Path | None = None,
        calibration_input_path: str | Path | None = None,
        aircraft_db_processed_path: str | Path | None = None,
    ) -> dict[str, Path]:
        AviationAllocationBuilder(airport_metadata_path=Path(airport_metadata_path)).build(
            processed_flightlist_path=self.paths.processed_dir
            / "opensky_flightlist_processed.parquet",
            aircraft_db_processed_path=aircraft_db_processed_path,
            output_dir=self.paths.processed_dir,
        )
        AviationBaselineBuilder().build(
            stock_input_path=stock_input_path,
            technology_catalog_path=technology_catalog_path,
            calibration_targets_path=self.paths.processed_dir / "aviation_calibration_targets.csv"
            if calibration_input_path is not None
            else None,
            output_stock_path=self.paths.processed_dir / "aviation_fleet_stock_enriched.csv",
            output_activity_profiles_path=self.paths.processed_dir
            / "aviation_activity_profiles.csv",
        )
        if calibration_input_path is not None:
            AviationCalibrationBuilder().build(
                calibration_input_path=calibration_input_path,
                enriched_stock_path=self.paths.processed_dir / "aviation_fleet_stock_enriched.csv",
                output_path=self.paths.processed_dir / "aviation_calibration_targets.csv",
            )
            AviationBaselineBuilder().build(
                stock_input_path=stock_input_path,
                technology_catalog_path=technology_catalog_path,
                calibration_targets_path=self.paths.processed_dir
                / "aviation_calibration_targets.csv",
                output_stock_path=self.paths.processed_dir / "aviation_fleet_stock_enriched.csv",
                output_activity_profiles_path=self.paths.processed_dir
                / "aviation_activity_profiles.csv",
            )
        return {
            "airport_allocation": self.paths.processed_dir / "aviation_airport_allocation.csv",
            "regional_allocation": self.paths.processed_dir / "aviation_regional_allocation.csv",
            "calibration_targets": self.paths.processed_dir / "aviation_calibration_targets.csv",
            "enriched_stock": self.paths.processed_dir / "aviation_fleet_stock_enriched.csv",
            "activity_profiles": self.paths.processed_dir / "aviation_activity_profiles.csv",
        }
