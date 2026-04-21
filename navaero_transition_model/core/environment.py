from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from navaero_transition_model.core.policy import PolicySignal


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _read_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    raw_value = row.get(key)
    if raw_value in (None, ""):
        return float(default)
    return float(raw_value.strip().replace(",", ""))


def _read_text(row: dict[str, str], key: str, default: str = "unknown") -> str:
    raw_value = row.get(key)
    if raw_value in (None, ""):
        return default
    return raw_value.strip()


def _bounded(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


@dataclass
class CountryEnvironmentState:
    country: str
    aviation_infrastructure: float
    maritime_infrastructure: float
    aviation_clean_fuel_availability: float
    maritime_clean_fuel_availability: float
    policy_alignment: float


@dataclass(frozen=True)
class CountryEnvironmentSignal:
    infrastructure_readiness: float
    clean_fuel_availability: float
    policy_alignment: float
    corridor_exposure: float


@dataclass(frozen=True)
class Corridor:
    origin_country: str
    destination_country: str
    sector_name: str
    connectivity: float
    clean_fuel_corridor: float


class TransitionEnvironment:
    """Shared world layer connecting countries, corridors, and sector conditions."""

    def __init__(
        self,
        countries: dict[str, CountryEnvironmentState],
        corridors: list[Corridor],
    ) -> None:
        self.countries = countries
        self.corridors = corridors

    @classmethod
    def from_csvs(
        cls,
        countries_path: str | Path | None,
        corridors_path: str | Path | None,
    ) -> TransitionEnvironment:
        countries = cls._load_countries(countries_path)
        corridors = cls._load_corridors(corridors_path)
        return cls(countries=countries, corridors=corridors)

    @staticmethod
    def _load_countries(path: str | Path | None) -> dict[str, CountryEnvironmentState]:
        if path is None:
            return {}

        csv_path = Path(path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Country environment file not found: {csv_path}")

        countries: dict[str, CountryEnvironmentState] = {}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                country = _read_text(row, "country")
                countries[country] = CountryEnvironmentState(
                    country=country,
                    aviation_infrastructure=_bounded(
                        _read_float(row, "aviation_infrastructure", 0.25),
                    ),
                    maritime_infrastructure=_bounded(
                        _read_float(row, "maritime_infrastructure", 0.25),
                    ),
                    aviation_clean_fuel_availability=_bounded(
                        _read_float(row, "aviation_clean_fuel_availability", 0.20),
                    ),
                    maritime_clean_fuel_availability=_bounded(
                        _read_float(row, "maritime_clean_fuel_availability", 0.20),
                    ),
                    policy_alignment=_bounded(_read_float(row, "policy_alignment", 0.50)),
                )

        return countries

    @staticmethod
    def _load_corridors(path: str | Path | None) -> list[Corridor]:
        if path is None:
            return []

        csv_path = Path(path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Corridor environment file not found: {csv_path}")

        corridors: list[Corridor] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                corridors.append(
                    Corridor(
                        origin_country=_read_text(row, "origin_country"),
                        destination_country=_read_text(row, "destination_country"),
                        sector_name=_read_text(row, "sector_name"),
                        connectivity=_bounded(_read_float(row, "connectivity", 0.5)),
                        clean_fuel_corridor=_bounded(
                            _read_float(row, "clean_fuel_corridor", 0.25),
                        ),
                    )
                )
        return corridors

    def ensure_country(self, country: str) -> CountryEnvironmentState:
        if country not in self.countries:
            average_state = self.average_country_state()
            self.countries[country] = CountryEnvironmentState(
                country=country,
                aviation_infrastructure=average_state.aviation_infrastructure,
                maritime_infrastructure=average_state.maritime_infrastructure,
                aviation_clean_fuel_availability=average_state.aviation_clean_fuel_availability,
                maritime_clean_fuel_availability=average_state.maritime_clean_fuel_availability,
                policy_alignment=average_state.policy_alignment,
            )
        return self.countries[country]

    def average_country_state(self) -> CountryEnvironmentState:
        if not self.countries:
            return CountryEnvironmentState(
                country="average",
                aviation_infrastructure=0.25,
                maritime_infrastructure=0.25,
                aviation_clean_fuel_availability=0.20,
                maritime_clean_fuel_availability=0.20,
                policy_alignment=0.50,
            )

        states = list(self.countries.values())
        return CountryEnvironmentState(
            country="average",
            aviation_infrastructure=_mean([state.aviation_infrastructure for state in states]),
            maritime_infrastructure=_mean([state.maritime_infrastructure for state in states]),
            aviation_clean_fuel_availability=_mean(
                [state.aviation_clean_fuel_availability for state in states],
            ),
            maritime_clean_fuel_availability=_mean(
                [state.maritime_clean_fuel_availability for state in states],
            ),
            policy_alignment=_mean([state.policy_alignment for state in states]),
        )

    def corridor_exposure(self, country: str, sector_name: str) -> float:
        relevant = [
            corridor
            for corridor in self.corridors
            if corridor.sector_name == sector_name
            and country in {corridor.origin_country, corridor.destination_country}
        ]
        if not relevant:
            return 0.0

        return _mean(
            [
                0.6 * corridor.connectivity + 0.4 * corridor.clean_fuel_corridor
                for corridor in relevant
            ],
        )

    def signal_for(self, country: str, sector_name: str) -> CountryEnvironmentSignal:
        state = self.ensure_country(country)
        corridor_exposure = self.corridor_exposure(country, sector_name)

        if sector_name == "aviation":
            infrastructure = state.aviation_infrastructure
            clean_fuel = state.aviation_clean_fuel_availability
        else:
            infrastructure = state.maritime_infrastructure
            clean_fuel = state.maritime_clean_fuel_availability

        return CountryEnvironmentSignal(
            infrastructure_readiness=_bounded(infrastructure + 0.10 * corridor_exposure),
            clean_fuel_availability=_bounded(clean_fuel + 0.20 * corridor_exposure),
            policy_alignment=state.policy_alignment,
            corridor_exposure=corridor_exposure,
        )

    def update(self, policy_signal: PolicySignal, agents: list) -> None:
        grouped_agents: dict[tuple[str, str], list] = {}
        for agent in agents:
            key = (agent.operator_country, agent.sector_name)
            grouped_agents.setdefault(key, []).append(agent)

        for (country, sector_name), country_agents in grouped_agents.items():
            state = self.ensure_country(country)
            average_share = _mean([agent.alternative_share for agent in country_agents])
            average_pressure = _mean([agent.transition_pressure for agent in country_agents])
            corridor_exposure = self.corridor_exposure(country, sector_name)

            if sector_name == "aviation":
                state.aviation_infrastructure = _bounded(
                    state.aviation_infrastructure
                    + 0.03 * policy_signal.aviation.clean_fuel_subsidy
                    + 0.02 * average_share
                    + 0.02 * corridor_exposure,
                )
                state.aviation_clean_fuel_availability = _bounded(
                    state.aviation_clean_fuel_availability
                    + 0.03 * policy_signal.aviation.clean_fuel_subsidy
                    + 0.02 * average_pressure,
                )
            else:
                state.maritime_infrastructure = _bounded(
                    state.maritime_infrastructure
                    + 0.03 * policy_signal.maritime.clean_fuel_subsidy
                    + 0.02 * average_share
                    + 0.02 * corridor_exposure,
                )
                state.maritime_clean_fuel_availability = _bounded(
                    state.maritime_clean_fuel_availability
                    + 0.03 * policy_signal.maritime.clean_fuel_subsidy
                    + 0.02 * average_pressure,
                )

            state.policy_alignment = _bounded(
                0.75 * state.policy_alignment
                + 0.25
                * (
                    0.5
                    + 0.25 * policy_signal.carbon_price / max(policy_signal.carbon_price, 180.0)
                    + 0.25 * average_share
                ),
            )
