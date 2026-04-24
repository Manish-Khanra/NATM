from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class OpenAPPreprocessingConfig:
    estimate_fuel: bool = False
    mode: str = "synthetic"
    route_extension_factor: float = 1.05
    include_non_co2: bool = True

    @classmethod
    def from_dict(cls, payload: dict | None) -> OpenAPPreprocessingConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("preprocessing.aviation.openap must be a mapping")
        return cls(
            estimate_fuel=bool(payload.get("estimate_fuel", False)),
            mode=str(payload.get("mode", "synthetic")),
            route_extension_factor=float(payload.get("route_extension_factor", 1.05)),
            include_non_co2=bool(payload.get("include_non_co2", True)),
        )


@dataclass(frozen=True)
class AviationPreprocessingConfig:
    enabled: bool = False
    stock_input: str | None = None
    opensky_raw: str | None = None
    flightlist_folder: str | None = None
    airport_metadata: str | None = None
    technology_catalog: str | None = None
    calibration_input: str | None = None
    processed_dir: str | None = None
    openap: OpenAPPreprocessingConfig = field(default_factory=OpenAPPreprocessingConfig)

    @classmethod
    def from_dict(cls, payload: dict | None) -> AviationPreprocessingConfig:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("preprocessing.aviation must be a mapping")
        return cls(
            enabled=bool(payload.get("enabled", False)),
            stock_input=_optional_text(payload.get("stock_input")),
            opensky_raw=_optional_text(payload.get("opensky_raw")),
            flightlist_folder=_optional_text(payload.get("flightlist_folder")),
            airport_metadata=_optional_text(payload.get("airport_metadata")),
            technology_catalog=_optional_text(payload.get("technology_catalog")),
            calibration_input=_optional_text(payload.get("calibration_input")),
            processed_dir=_optional_text(payload.get("processed_dir")),
            openap=OpenAPPreprocessingConfig.from_dict(payload.get("openap")),
        )

    def resolve_path(self, base_path: Path, field_name: str) -> Path | None:
        value = getattr(self, field_name)
        if value is None:
            return None
        return (base_path / value).resolve()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class NATMScenario:
    name: str
    start_year: int
    end_year: int
    sectors: dict[str, tuple[str, ...]]
    preprocessing: dict[str, AviationPreprocessingConfig] = field(default_factory=dict)
    base_path: Path = field(default_factory=lambda: Path("."), repr=False)

    def __post_init__(self) -> None:
        if self.end_year < self.start_year:
            raise ValueError("end_year must be greater than or equal to start_year")
        if not self.sectors:
            raise ValueError("sectors must include at least one sector")

        unsupported = set(self.sectors) - {"aviation", "maritime"}
        if unsupported:
            unsupported_text = ", ".join(sorted(unsupported))
            raise ValueError(f"Unsupported sectors in sectors: {unsupported_text}")

    @property
    def enabled_sectors(self) -> tuple[str, ...]:
        return tuple(self.sectors.keys())

    @property
    def steps(self) -> int:
        return self.end_year - self.start_year + 1

    def is_sector_enabled(self, sector_name: str) -> bool:
        return sector_name in self.sectors

    def applications_for_sector(self, sector_name: str) -> tuple[str, ...]:
        return self.sectors.get(sector_name, ())

    def is_application_enabled(self, sector_name: str, application_name: str) -> bool:
        return application_name in self.applications_for_sector(sector_name)

    def operator_input_path(self, sector_name: str) -> Path | None:
        default_path = self.base_path / f"{sector_name}_operators.csv"
        if default_path.exists():
            return default_path.resolve()
        return None

    def environment_input_path(self, name: str) -> Path | None:
        default_path = self.base_path / f"{name}.csv"
        if default_path.exists():
            return default_path.resolve()
        return None

    def aviation_preprocessing_config(self) -> AviationPreprocessingConfig | None:
        return self.preprocessing.get("aviation")

    @classmethod
    def from_dict(cls, payload: dict) -> NATMScenario:
        raw_sectors = payload.get("sectors")
        if not isinstance(raw_sectors, dict) or not raw_sectors:
            raise ValueError("scenario.yaml must define sectors as a mapping")

        normalized_sectors: dict[str, tuple[str, ...]] = {}
        for sector_name, applications in raw_sectors.items():
            if applications is None:
                normalized_sectors[str(sector_name)] = ()
                continue
            if not isinstance(applications, list):
                raise ValueError(f"Sector '{sector_name}' must map to a list of applications")
            normalized_sectors[str(sector_name)] = tuple(str(item).strip() for item in applications)

        preprocessing = _parse_preprocessing(payload.get("preprocessing"))

        return cls(
            name=payload["name"],
            start_year=payload["start_year"],
            end_year=payload["end_year"],
            sectors=normalized_sectors,
            preprocessing=preprocessing,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> NATMScenario:
        scenario_path = Path(path)
        payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        scenario = cls.from_dict(payload)
        scenario.base_path = scenario_path.parent.resolve()
        return scenario


def _parse_preprocessing(payload: object) -> dict[str, AviationPreprocessingConfig]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("preprocessing must be a mapping")

    unsupported = set(payload) - {"aviation"}
    if unsupported:
        unsupported_text = ", ".join(sorted(str(item) for item in unsupported))
        raise ValueError(f"Unsupported preprocessing sections: {unsupported_text}")

    aviation_payload = payload.get("aviation")
    if aviation_payload is None:
        return {}
    return {"aviation": AviationPreprocessingConfig.from_dict(aviation_payload)}
