"""Internal rule contract shared by scheduling, closure and advancement.

The two bracket codes and the formation catalog are **not configurable**: they
are part of the engine contract (spec 007, RF-050/RF-051) and are documented in
``docs/contrato-reglas.md`` with ``engine_version`` 2026.1. This module is the
single source of truth for those values; every consumer imports them here.

Keep this module free of imports from ``app.modules`` so it can be used by
``tournaments``, ``matches`` and ``advancement`` without cycles.
"""

from typing import Final


ENGINE_VERSION: Final = "2026.1"

# Double-elimination finale: GF1 is the grand final and GF2 its repetition
# (the "bracket reset") created as a cancelled match by the scheduler.
GRAND_FINAL_CODE: Final = "GF1"
RESET_CODE: Final = "GF2"
GRAND_FINAL_CODES: Final[frozenset[str]] = frozenset({GRAND_FINAL_CODE, RESET_CODE})

# Closed catalog: API validation and the database CHECK accept exactly these
# four formations, and no other. The tuple order is the documented order.
FORMATION_SLOTS: Final[dict[str, tuple[str, ...]]] = {
    "4-3-3": (
        "GK",
        "LB",
        "LCB",
        "RCB",
        "RB",
        "CM_L",
        "CM",
        "CM_R",
        "LW",
        "ST",
        "RW",
    ),
    "4-4-2": (
        "GK",
        "LB",
        "LCB",
        "RCB",
        "RB",
        "LM",
        "LCM",
        "RCM",
        "RM",
        "ST_L",
        "ST_R",
    ),
    "3-5-2": (
        "GK",
        "LCB",
        "CB",
        "RCB",
        "LWB",
        "LCM",
        "CM",
        "RCM",
        "RWB",
        "ST_L",
        "ST_R",
    ),
    "4-2-3-1": (
        "GK",
        "LB",
        "LCB",
        "RCB",
        "RB",
        "CDM_L",
        "CDM_R",
        "LW",
        "CAM",
        "RW",
        "ST",
    ),
}

FORMATION_CODES: Final[tuple[str, ...]] = tuple(FORMATION_SLOTS)


def slots_for_formation(formation_code: str) -> tuple[str, ...] | None:
    """Return the positions of a catalog formation, or ``None`` if unknown."""

    return FORMATION_SLOTS.get(formation_code)


def requires_decisive_winner(bracket_code: str | None) -> bool:
    """GF1 and its repetition must close with a winner (RF-052)."""

    return bracket_code in GRAND_FINAL_CODES
