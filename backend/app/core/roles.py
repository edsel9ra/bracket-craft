"""Declared role precedence (R32b, RF-016).

The displayed role of a member with several roles follows a single declared
order: owner > administrator > operator > referee > viewer. The role is
informative: authorization stays additive by permissions and ``match_officials``
(M8).

A role code that is unknown, or a member without roles, resolves to the last
entry (``viewer``), which is also the default the member listing already used.
"""

from __future__ import annotations


ROLE_PRECEDENCE: tuple[str, ...] = (
    "owner",
    "administrator",
    "operator",
    "referee",
    "viewer",
)
DEFAULT_ROLE_CODE = ROLE_PRECEDENCE[-1]


def role_precedence_index(code: str | None) -> int:
    """Return the precedence index of ``code``; unknown codes are viewers."""

    if code in ROLE_PRECEDENCE:
        return ROLE_PRECEDENCE.index(code)
    return ROLE_PRECEDENCE.index(DEFAULT_ROLE_CODE)


#: Reusable SQL expression: ``ROLE_PRECEDENCE_SQL.format(column="rd.code")``.
#: It is generated from ``ROLE_PRECEDENCE`` so the order is declared once.
ROLE_PRECEDENCE_SQL = "CASE {column} " + " ".join(
    f"WHEN '{code}' THEN {index}" for index, code in enumerate(ROLE_PRECEDENCE)
) + f" ELSE {role_precedence_index(None)} END"
