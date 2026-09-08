from typing import Final


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


def slots_for_formation(formation_code: str) -> tuple[str, ...] | None:
    return FORMATION_SLOTS.get(formation_code)
