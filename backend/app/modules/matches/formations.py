"""Backwards-compatible import path for the formation catalog.

The single source is :mod:`app.modules.rule_contract` (RF-051). This module
keeps the historical import path used by the matches router, the demo seed and
the tests.
"""

from app.modules.rule_contract import (
    FORMATION_CODES,
    FORMATION_SLOTS,
    slots_for_formation,
)

__all__ = ["FORMATION_CODES", "FORMATION_SLOTS", "slots_for_formation"]
