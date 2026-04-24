from __future__ import annotations

import math

import pandas as pd

from navaero_transition_model.aviation_preprocessing.openap_backend import OpenAPFuelConfig

KNOT_TO_KM_PER_H = 1.852


def _is_turboprop_or_regional(openap_type: str) -> bool:
    normalized = str(openap_type).upper().strip()
    return normalized.startswith(("AT", "ATR", "DH8", "CRJ", "E1"))


def _cruise_altitude(distance_km: float, config: OpenAPFuelConfig) -> int:
    if distance_km < config.short_distance_threshold_km:
        return config.cruise_altitude_short_ft
    if distance_km < config.medium_distance_threshold_km:
        return config.cruise_altitude_medium_ft
    return config.cruise_altitude_long_ft


def _cruise_tas(openap_type: str, distance_km: float) -> float:
    if _is_turboprop_or_regional(openap_type):
        return 300.0 if distance_km > 300.0 else 270.0
    return 460.0 if distance_km > 800.0 else 430.0


def _phase_rows(
    *,
    phase: str,
    duration_seconds: float,
    tas_kt: float,
    alt_ft: float,
    vs_fpm: float,
    time_step_seconds: int,
) -> list[dict[str, float | str]]:
    duration_seconds = max(float(duration_seconds), 0.0)
    if duration_seconds <= 0.0:
        return []
    step_count = max(int(math.ceil(duration_seconds / time_step_seconds)), 1)
    rows: list[dict[str, float | str]] = []
    remaining = duration_seconds
    for _ in range(step_count):
        delta_t = min(float(time_step_seconds), remaining)
        if delta_t <= 0.0:
            break
        rows.append(
            {
                "phase": phase,
                "delta_t_seconds": delta_t,
                "tas_kt": float(tas_kt),
                "alt_ft": float(alt_ft),
                "vs_fpm": float(vs_fpm),
            }
        )
        remaining -= delta_t
    return rows


def generate_synthetic_mission_profile(
    distance_km: float,
    openap_type: str,
    config: OpenAPFuelConfig,
) -> pd.DataFrame:
    route_distance = max(float(distance_km), 0.0)
    flown_distance_km = route_distance * float(config.route_extension_factor)
    cruise_altitude_ft = float(_cruise_altitude(route_distance, config))

    if _is_turboprop_or_regional(openap_type):
        climb_rate = float(config.climb_rate_turboprop_fpm)
        descent_rate = float(config.descent_rate_turboprop_fpm)
    else:
        climb_rate = float(config.climb_rate_jet_fpm)
        descent_rate = float(config.descent_rate_jet_fpm)

    climb_tas_kt = 275.0
    descent_tas_kt = 290.0
    cruise_tas_kt = _cruise_tas(openap_type, route_distance)

    while cruise_altitude_ft > 6000:
        climb_time_h = (cruise_altitude_ft / climb_rate) / 60.0
        descent_time_h = (cruise_altitude_ft / abs(descent_rate)) / 60.0
        climb_distance = climb_tas_kt * KNOT_TO_KM_PER_H * climb_time_h
        descent_distance = descent_tas_kt * KNOT_TO_KM_PER_H * descent_time_h
        cruise_distance = flown_distance_km - climb_distance - descent_distance
        if cruise_distance >= 0.0:
            break
        cruise_altitude_ft -= 3000

    climb_time_seconds = (cruise_altitude_ft / climb_rate) * 60.0
    descent_time_seconds = (cruise_altitude_ft / abs(descent_rate)) * 60.0
    cruise_distance = max(
        flown_distance_km
        - climb_tas_kt * KNOT_TO_KM_PER_H * (climb_time_seconds / 3600.0)
        - descent_tas_kt * KNOT_TO_KM_PER_H * (descent_time_seconds / 3600.0),
        0.0,
    )
    cruise_time_seconds = (
        cruise_distance / max(cruise_tas_kt * KNOT_TO_KM_PER_H, 1e-6)
    ) * 3600.0

    rows: list[dict[str, float | str]] = []
    rows.extend(
        _phase_rows(
            phase="climb",
            duration_seconds=climb_time_seconds,
            tas_kt=climb_tas_kt,
            alt_ft=cruise_altitude_ft * 0.5,
            vs_fpm=climb_rate,
            time_step_seconds=config.time_step_seconds,
        )
    )
    rows.extend(
        _phase_rows(
            phase="cruise",
            duration_seconds=cruise_time_seconds,
            tas_kt=cruise_tas_kt,
            alt_ft=cruise_altitude_ft,
            vs_fpm=0.0,
            time_step_seconds=config.time_step_seconds,
        )
    )
    rows.extend(
        _phase_rows(
            phase="descent",
            duration_seconds=descent_time_seconds,
            tas_kt=descent_tas_kt,
            alt_ft=cruise_altitude_ft * 0.5,
            vs_fpm=descent_rate,
            time_step_seconds=config.time_step_seconds,
        )
    )

    profile = pd.DataFrame(
        rows,
        columns=["phase", "delta_t_seconds", "tas_kt", "alt_ft", "vs_fpm"],
    )
    profile["flown_distance_km"] = flown_distance_km
    if cruise_distance <= 0.0:
        profile["profile_quality_flag"] = "short_route_adjusted_profile"
    else:
        profile["profile_quality_flag"] = ""
    return profile
