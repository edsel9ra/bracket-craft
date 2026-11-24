"""Backwards-compatible import path for the formation catalog.

The single source is :mod:`app.modules.rule_contract` (RF-051). This module
keeps the historical import path used by the matches router, the demo seed and
the tests.
"""

from app.modules.rule_contract import (
    DEFAULT_GAME_FORMAT,
    FORMATION_CODES,
    FORMATION_SLOTS,
    FORMATIONS_BY_GAME_FORMAT,
    formation_game_format,
    slots_for_formation,
    starters_for_game_format,
)

__all__ = [
    "DEFAULT_GAME_FORMAT",
    "FORMATION_CODES",
    "FORMATION_SLOTS",
    "FORMATIONS_BY_GAME_FORMAT",
    "formation_game_format",
    "slots_for_formation",
    "starters_for_game_format",
]
