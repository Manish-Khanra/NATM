from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class AircraftTypeMappingResult:
    raw_type: str
    openap_type: str | None
    mapping_status: str
    mapping_note: str


def _normalize_aircraft_type(raw_type: object) -> str:
    if raw_type is None:
        return ""
    normalized = str(raw_type).strip().upper().replace("-", "").replace(" ", "")
    return normalized


@lru_cache(maxsize=512)
def is_openap_supported(ac_code: str) -> bool:
    normalized = _normalize_aircraft_type(ac_code)
    if not normalized:
        return False
    try:
        import openap  # type: ignore[import-not-found]

        openap.prop.aircraft(normalized)
    except Exception:
        return False
    return True


FALLBACK_CANDIDATES: dict[str, tuple[str, ...]] = {
    "A20N": ("A20N", "A320"),
    "A21N": ("A21N", "A321"),
    "A320": ("A320",),
    "A321": ("A321",),
    "A319": ("A319",),
    "A359": ("A359", "A333", "A332"),
    "B738": ("B738",),
    "B38M": ("B38M", "B738"),
    "B39M": ("B39M", "B739", "B738"),
    "B737": ("B737", "B738"),
    "B739": ("B739", "B738"),
    "B789": ("B789", "B788"),
    "B788": ("B788",),
    "B77W": ("B77W", "B772"),
    "E190": ("E190",),
    "E195": ("E195", "E190"),
    "CRJ9": ("CRJ9", "CRJ7", "CRJ2"),
    "CRJ7": ("CRJ7", "CRJ2"),
    "CRJ2": ("CRJ2",),
    "AT72": ("AT72", "ATR72"),
    "ATR72": ("ATR72", "AT72"),
    # Verified against OpenAP's own coverage (openap.prop.aircraft) directly -
    # these codes appeared as real, common "unsupported_aircraft_type" flags in
    # actual flight data with no fallback attempted at all (not even OpenAP-checked).
    "A306": ("A306", "B763"),  # A300-600: no OpenAP model; closest weight-class twin
    "B77L": ("B77L", "B77W", "B772"),  # 777-200LR/777F
    "A339": ("A339", "A333", "A332"),  # A330-900neo
    "A346": ("A346", "A345", "A343"),  # A340-600
    # DH8D (Dash 8-400): this OpenAP installation has no turboprop coverage at
    # all - DH8A/B/C and ATR72/AT72 are all unsupported too (verified directly),
    # so the existing "AT72"/"ATR72" entries above were already non-functional
    # before this change. Left as genuinely unsupported rather than implying a
    # fallback that doesn't work.
    "DH8D": ("DH8D", "DH8C", "DH8A"),
}


def map_to_openap_type(raw_type: str) -> AircraftTypeMappingResult:
    normalized = _normalize_aircraft_type(raw_type)
    if not normalized:
        return AircraftTypeMappingResult(
            raw_type=str(raw_type or ""),
            openap_type=None,
            mapping_status="missing",
            mapping_note="Missing aircraft type.",
        )

    candidates = FALLBACK_CANDIDATES.get(normalized, (normalized,))
    for index, candidate in enumerate(candidates):
        if is_openap_supported(candidate):
            if index == 0 and candidate == normalized:
                return AircraftTypeMappingResult(
                    raw_type=normalized,
                    openap_type=candidate,
                    mapping_status="exact",
                    mapping_note=f"{normalized} is supported by OpenAP.",
                )
            return AircraftTypeMappingResult(
                raw_type=normalized,
                openap_type=candidate,
                mapping_status="fallback",
                mapping_note=f"{normalized} is not supported; using {candidate}.",
            )

    return AircraftTypeMappingResult(
        raw_type=normalized,
        openap_type=None,
        mapping_status="unsupported",
        mapping_note=f"No supported OpenAP type found for {normalized}.",
    )
