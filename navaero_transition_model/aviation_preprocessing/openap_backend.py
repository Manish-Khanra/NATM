from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class OpenAPFuelConfig:
    route_extension_factor: float = 1.05
    default_mass_fraction_of_mtow: float = 0.85
    min_mass_fraction_of_mtow: float = 0.55
    jet_a_lhv_mj_per_kg: float = 43.0
    co2_factor_kg_per_kg_fuel: float = 3.16
    include_non_co2: bool = True
    use_groundspeed_as_tas_proxy: bool = True
    short_distance_threshold_km: float = 300.0
    medium_distance_threshold_km: float = 800.0
    cruise_altitude_short_ft: int = 20000
    cruise_altitude_medium_ft: int = 30000
    cruise_altitude_long_ft: int = 35000
    climb_rate_jet_fpm: float = 1800.0
    descent_rate_jet_fpm: float = -1800.0
    climb_rate_turboprop_fpm: float = 1200.0
    descent_rate_turboprop_fpm: float = -1200.0
    time_step_seconds: int = 60
    economy_passenger_mass_kg: float = 95.0
    business_passenger_mass_kg: float = 105.0
    first_passenger_mass_kg: float = 115.0
    default_passenger_mass_kg: float = 100.0
    block_fuel_reserve_factor: float = 1.15
    default_cargo_load_factor: float = 0.70
    use_data_driven_initial_mass: bool = True


@dataclass(frozen=True)
class InitialMassEstimate:
    initial_mass_kg: float
    min_mass_kg: float
    mtow_kg: float
    oew_kg: float
    passenger_payload_kg: float
    cargo_payload_kg: float
    estimated_block_fuel_kg: float
    mass_estimation_method: str


DEFAULT_MTOW_KG = {
    "A319": 75500.0,
    "A320": 78000.0,
    "A20N": 79000.0,
    "A321": 93500.0,
    "A21N": 97000.0,
    "A359": 280000.0,
    "B737": 70500.0,
    "B738": 79000.0,
    "B739": 85100.0,
    "B38M": 82190.0,
    "B39M": 88300.0,
    "B788": 227930.0,
    "B789": 254000.0,
    "B77W": 351500.0,
    "E190": 51800.0,
    "E195": 52290.0,
    "CRJ2": 24040.0,
    "CRJ7": 34020.0,
    "CRJ9": 38330.0,
    "AT72": 23000.0,
    "ATR72": 23000.0,
    "DH8D": 29260.0,
}


@dataclass
class OpenAPFuelEmissionBackend:
    config: OpenAPFuelConfig
    assumption_log: list[str] = field(default_factory=list)
    last_quality_flags: set[str] = field(default_factory=set)

    def _reset_last_flags(self) -> None:
        self.last_quality_flags = set()

    @staticmethod
    @lru_cache(maxsize=512)
    def _aircraft_properties_cached(openap_type: str) -> dict[str, Any]:
        try:
            import openap  # type: ignore[import-not-found]

            properties = openap.prop.aircraft(openap_type)
        except Exception:
            return {}
        return properties if isinstance(properties, dict) else {}

    def get_aircraft_properties(self, openap_type: str) -> dict[str, Any]:
        properties = self._aircraft_properties_cached(str(openap_type).upper().strip())
        return dict(properties)

    def _mtow_from_properties(self, openap_type: str) -> float:
        properties = self.get_aircraft_properties(openap_type)
        candidates = [
            properties.get("mtow"),
            properties.get("MTOW"),
            properties.get("mto"),
            properties.get("max_takeoff_weight"),
        ]
        limits = properties.get("limits")
        if isinstance(limits, dict):
            candidates.extend([limits.get("MTOW"), limits.get("mtow")])
        for candidate in candidates:
            value = pd.to_numeric(pd.Series([candidate]), errors="coerce").iloc[0]
            if pd.notna(value) and float(value) > 0:
                return float(value)

        fallback = DEFAULT_MTOW_KG.get(str(openap_type).upper().strip(), 75000.0)
        self.assumption_log.append(f"Using fallback MTOW {fallback:.0f} kg for {openap_type}.")
        return fallback

    @staticmethod
    def _numeric_value(row: pd.Series, names: tuple[str, ...]) -> float | None:
        for name in names:
            if name not in row.index:
                continue
            value = pd.to_numeric(pd.Series([row.get(name)]), errors="coerce").iloc[0]
            if pd.notna(value) and float(value) > 0.0:
                return float(value)
        return None

    def _fallback_initial_mass_estimate(self, openap_type: str) -> InitialMassEstimate:
        mtow = self._mtow_from_properties(openap_type)
        min_mass = self.config.min_mass_fraction_of_mtow * mtow
        return InitialMassEstimate(
            initial_mass_kg=self.config.default_mass_fraction_of_mtow * mtow,
            min_mass_kg=min_mass,
            mtow_kg=mtow,
            oew_kg=0.0,
            passenger_payload_kg=0.0,
            cargo_payload_kg=0.0,
            estimated_block_fuel_kg=0.0,
            mass_estimation_method="mtow_fraction_fallback",
        )

    def estimate_initial_mass(self, openap_type: str) -> float:
        return self._fallback_initial_mass_estimate(openap_type).initial_mass_kg

    def estimate_min_mass(self, openap_type: str) -> float:
        mtow = self._mtow_from_properties(openap_type)
        return self.config.min_mass_fraction_of_mtow * mtow

    def estimate_initial_mass_from_context(
        self,
        *,
        openap_type: str,
        flight_row: pd.Series,
        distance_km: float,
        flown_distance_km: float,
        application_name: str = "passenger",
    ) -> InitialMassEstimate:
        if not self.config.use_data_driven_initial_mass:
            return self._fallback_initial_mass_estimate(openap_type)

        fallback = self._fallback_initial_mass_estimate(openap_type)
        mtow = self._numeric_value(flight_row, ("technology_mtow", "mtow")) or fallback.mtow_kg
        oew = self._numeric_value(flight_row, ("technology_oew", "oew"))
        if oew is None:
            return fallback

        passenger_payload = self._estimate_passenger_payload(flight_row)
        cargo_payload = self._estimate_cargo_payload(flight_row, application_name)
        minimum_physical_mass = oew + passenger_payload + cargo_payload
        min_mass = minimum_physical_mass
        block_fuel = self._estimate_block_fuel(
            flight_row=flight_row,
            distance_km=distance_km,
            flown_distance_km=flown_distance_km,
        )
        raw_mass = oew + passenger_payload + cargo_payload + block_fuel
        if raw_mass <= 0.0:
            return fallback

        initial_mass = min(max(raw_mass, min_mass), mtow)
        method_parts = ["oew_payload_block_fuel"]
        if initial_mass == mtow:
            method_parts.append("clamped_to_mtow")
        elif initial_mass == min_mass:
            method_parts.append("clamped_to_min_mass")
        return InitialMassEstimate(
            initial_mass_kg=initial_mass,
            min_mass_kg=min_mass,
            mtow_kg=mtow,
            oew_kg=oew,
            passenger_payload_kg=passenger_payload,
            cargo_payload_kg=cargo_payload,
            estimated_block_fuel_kg=block_fuel,
            mass_estimation_method="+".join(method_parts),
        )

    def _estimate_passenger_payload(self, row: pd.Series) -> float:
        economy_seats = self._numeric_value(row, ("technology_economy_seats", "economy_seats"))
        business_seats = self._numeric_value(row, ("technology_business_seats", "business_seats"))
        first_seats = self._numeric_value(
            row,
            ("technology_first_class_seats", "first_class_seats"),
        )
        economy_occupancy = self._numeric_value(row, ("economy_occupancy",)) or 0.0
        business_occupancy = self._numeric_value(row, ("business_occupancy",)) or 0.0
        first_occupancy = self._numeric_value(row, ("first_occupancy",)) or 0.0

        cabin_payload = (
            (economy_seats or 0.0)
            * economy_occupancy
            * self.config.economy_passenger_mass_kg
            + (business_seats or 0.0)
            * business_occupancy
            * self.config.business_passenger_mass_kg
            + (first_seats or 0.0)
            * first_occupancy
            * self.config.first_passenger_mass_kg
        )
        if cabin_payload > 0.0:
            return cabin_payload

        seat_total = self._numeric_value(row, ("seat_total",))
        if seat_total is None:
            return 0.0
        load_factor = (
            economy_occupancy
            or business_occupancy
            or first_occupancy
            or self._numeric_value(row, ("load_factor",))
            or 0.0
        )
        return seat_total * load_factor * self.config.default_passenger_mass_kg

    def _estimate_cargo_payload(self, row: pd.Series, application_name: str) -> float:
        if str(application_name).lower().strip() != "cargo":
            return 0.0
        payload_capacity = self._numeric_value(
            row,
            ("technology_payload_capacity_kg", "payload_capacity_kg"),
        )
        if payload_capacity is None:
            return 0.0
        load_factor = (
            self._numeric_value(row, ("load_factor",))
            or self.config.default_cargo_load_factor
        )
        return payload_capacity * load_factor

    def _estimate_block_fuel(
        self,
        *,
        flight_row: pd.Series,
        distance_km: float,
        flown_distance_km: float,
    ) -> float:
        fuel_capacity_kwh = self._numeric_value(
            flight_row,
            ("technology_fuel_capacity_kwh", "fuel_capacity_kwh"),
        )
        if fuel_capacity_kwh is None:
            return 0.0
        aircraft_range_km = self._numeric_value(
            flight_row,
            ("range_km", "technology_range_km", "aircraft_range_km"),
        )
        if aircraft_range_km is None:
            aircraft_range_km = self._numeric_value(
                flight_row,
                ("technology_trip_length_km", "trip_length_km"),
            )
        if aircraft_range_km is None:
            return 0.0

        kwh_per_kg_fuel = self.config.jet_a_lhv_mj_per_kg / 3.6
        fuel_capacity_kg = fuel_capacity_kwh / kwh_per_kg_fuel
        mission_distance = max(float(flown_distance_km), float(distance_km), 0.0)
        mission_fraction = min(mission_distance / aircraft_range_km, 1.0)
        return fuel_capacity_kg * mission_fraction * self.config.block_fuel_reserve_factor

    def _fallback_fuel_flow_kg_per_s(
        self,
        openap_type: str,
        mass_kg: float,
        tas_kt: float,
        vs_fpm: float | None,
    ) -> float:
        mtow = max(self._mtow_from_properties(openap_type), 1.0)
        mass_factor = max(float(mass_kg) / mtow, 0.35)
        speed_factor = max(float(tas_kt), 120.0) / 430.0
        base_flow = max(mtow / 100000.0 * 0.85, 0.18)
        phase_factor = 1.0
        if vs_fpm is not None and vs_fpm > 300:
            phase_factor = 1.55
        elif vs_fpm is not None and vs_fpm < -300:
            phase_factor = 0.55
        return max(base_flow * mass_factor * speed_factor * phase_factor, 0.01)

    def fuel_flow_kg_per_s(
        self,
        openap_type: str,
        mass_kg: float,
        tas_kt: float,
        alt_ft: float,
        vs_fpm: float | None = None,
    ) -> float:
        self._reset_last_flags()
        try:
            import openap  # type: ignore[import-not-found]

            fuel_flow_model = openap.FuelFlow(str(openap_type).upper().strip())
            for kwargs in (
                {"mass": mass_kg, "tas": tas_kt, "alt": alt_ft, "vs": vs_fpm or 0.0},
                {"mass": mass_kg, "tas": tas_kt, "alt": alt_ft},
            ):
                try:
                    value = fuel_flow_model.enroute(**kwargs)
                    flow = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
                    if pd.notna(flow) and float(flow) > 0:
                        return float(flow)
                except TypeError:
                    continue
        except Exception:
            pass

        self.last_quality_flags.add("openap_failure")
        return self._fallback_fuel_flow_kg_per_s(openap_type, mass_kg, tas_kt, vs_fpm)

    def estimate_energy_mwh(self, fuel_kg: float) -> float:
        return float(fuel_kg) * self.config.jet_a_lhv_mj_per_kg / 3600.0

    def estimate_co2_kg(self, fuel_kg: float) -> float:
        return float(fuel_kg) * self.config.co2_factor_kg_per_kg_fuel

    def estimate_emissions(self, openap_type: str, fuel_kg: float) -> dict[str, float | str]:
        emissions: dict[str, float | str] = {
            "co2_kg": self.estimate_co2_kg(fuel_kg),
            "h2o_kg": 0.0,
            "nox_kg": 0.0,
            "co_kg": 0.0,
            "hc_kg": 0.0,
            "soot_kg": 0.0,
            "sox_kg": 0.0,
            "emission_quality_flag": "co2_factor",
        }
        if not self.config.include_non_co2:
            emissions["emission_quality_flag"] = "co2_only_disabled"
            return emissions

        try:
            import openap  # type: ignore[import-not-found]

            emission_model = openap.Emission(str(openap_type).upper().strip())
            for output_key, method_name in (
                ("h2o_kg", "h2o"),
                ("nox_kg", "nox"),
                ("co_kg", "co"),
                ("hc_kg", "hc"),
                ("soot_kg", "soot"),
                ("sox_kg", "sox"),
            ):
                method = getattr(emission_model, method_name, None)
                if method is None:
                    continue
                try:
                    value = method(fuel_kg)
                    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
                    if pd.notna(numeric) and float(numeric) >= 0:
                        emissions[output_key] = float(numeric)
                except Exception:
                    continue
            emissions["emission_quality_flag"] = "openap_best_effort"
        except Exception:
            emissions["emission_quality_flag"] = "emission_fallback_co2_only"
        return emissions
