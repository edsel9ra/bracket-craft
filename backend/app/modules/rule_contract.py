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
# formations, and no other. Each one belongs to a single game format (spec
# 044); the tuple order is the documented order. 11v11 keeps its original four.
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
    "1-2-1": ("GK", "CB", "LM", "RM", "ST"),
    "2-1-1": ("GK", "LCB", "RCB", "CM", "ST"),
    "2-2": ("GK", "LCB", "RCB", "ST_L", "ST_R"),
    "2-3-1": ("GK", "LCB", "RCB", "LM", "CM", "RM", "ST"),
    "3-2-1": ("GK", "LCB", "CB", "RCB", "LCM", "RCM", "ST"),
    "3-1-2": ("GK", "LCB", "CB", "RCB", "CM", "ST_L", "ST_R"),
    "3-3-2": ("GK", "LCB", "CB", "RCB", "LM", "CM", "RM", "ST_L", "ST_R"),
    "3-4-1": ("GK", "LCB", "CB", "RCB", "LM", "LCM", "RCM", "RM", "ST"),
    "4-3-1": ("GK", "LB", "LCB", "RCB", "RB", "CM_L", "CM", "CM_R", "ST"),
}


FORMATION_CODES: Final[tuple[str, ...]] = tuple(FORMATION_SLOTS)

DEFAULT_GAME_FORMAT: Final = "11v11"

FORMATIONS_BY_GAME_FORMAT: Final[dict[str, tuple[str, ...]]] = {
    "5v5": ("1-2-1", "2-1-1", "2-2"),
    "7v7": ("2-3-1", "3-2-1", "3-1-2"),
    "9v9": ("3-3-2", "3-4-1", "4-3-1"),
    "11v11": ("4-3-3", "4-4-2", "3-5-2", "4-2-3-1"),
}

_GAME_FORMAT_BY_FORMATION: Final[dict[str, str]] = {
    code: game_format for game_format, codes in FORMATIONS_BY_GAME_FORMAT.items() for code in codes
}

_STARTERS_BY_GAME_FORMAT: Final[dict[str, int]] = {"5v5": 5, "7v7": 7, "9v9": 9, "11v11": 11}


def formation_game_format(formation_code: str) -> str | None:
    """Game format a catalog formation belongs to, or ``None`` if unknown."""

    return _GAME_FORMAT_BY_FORMATION.get(formation_code)


def starters_for_game_format(game_format: str | None) -> int:
    """Starters of a formation in ``game_format``; absent reads as 11v11."""

    try:
        return _STARTERS_BY_GAME_FORMAT[game_format or DEFAULT_GAME_FORMAT]
    except KeyError:
        raise ValueError(f"unknown game format: {game_format!r}") from None


# Spec 052 (F17, D4): line of every catalog position. The public statistics
# derive the main position from it; the API returns the line code.
POSITION_LINE_CODES: Final[tuple[str, ...]] = ("goalkeeper", "defender", "midfielder", "forward")

POSITION_LINES: Final[dict[str, str]] = {
    "GK": "goalkeeper",
    **dict.fromkeys(("CB", "LCB", "RCB", "LB", "RB", "LWB", "RWB"), "defender"),
    **dict.fromkeys(("CDM_L", "CDM_R", "CM", "CM_L", "CM_R", "LCM", "RCM", "LM", "RM", "CAM"), "midfielder"),
    **dict.fromkeys(("ST", "ST_L", "ST_R", "LW", "RW"), "forward"),
}

_POSITIONS_BY_GAME_FORMAT: Final[dict[str, frozenset[str]]] = {
    game_format: frozenset(slot for code in codes for slot in FORMATION_SLOTS[code])
    for game_format, codes in FORMATIONS_BY_GAME_FORMAT.items()
}


def positions_for_game_format(game_format: str | None) -> frozenset[str]:
    """Positions of the formations of ``game_format`` (spec 052, D3); absent reads as 11v11."""

    try:
        return _POSITIONS_BY_GAME_FORMAT[game_format or DEFAULT_GAME_FORMAT]
    except KeyError:
        raise ValueError(f"unknown game format: {game_format!r}") from None


def slots_for_formation(formation_code: str) -> tuple[str, ...] | None:
    """Return the positions of a catalog formation, or ``None`` if unknown."""

    return FORMATION_SLOTS.get(formation_code)


def requires_decisive_winner(bracket_code: str | None) -> bool:
    """GF1 and its repetition must close with a winner (RF-052)."""

    return bracket_code in GRAND_FINAL_CODES
