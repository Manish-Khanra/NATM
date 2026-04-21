from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class NATMScenario:
    name: str
    start_year: int
    end_year: int
    sectors: dict[str, tuple[str, ...]]
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

        return cls(
            name=payload["name"],
            start_year=payload["start_year"],
            end_year=payload["end_year"],
            sectors=normalized_sectors,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> NATMScenario:
        scenario_path = Path(path)
        payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        scenario = cls.from_dict(payload)
        scenario.base_path = scenario_path.parent.resolve()
        return scenario
