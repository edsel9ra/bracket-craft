"""Catalog of tournament-scoped roles (spec 049).

Mirrors migration 069: ``tournament_member_roles.role_code`` and the fixed
permission set checked by ``public.tournament_operator_allows``.
"""

from __future__ import annotations

from uuid import UUID

TOURNAMENT_OPERATOR = "tournament_operator"
TOURNAMENT_ROLE_CODES: tuple[str, ...] = (TOURNAMENT_OPERATOR,)

TOURNAMENT_OPERATOR_PERMISSIONS: frozenset[str] = frozenset({
    "VIEW_MATCH_LIVE_DRAFT",
    "OPERATE_MATCH_LIVE",
    "CLOSE_MATCH_REPORT",
})

OPERATING_ORGANIZATION_ROLES: frozenset[str] = frozenset({"owner", "administrator", "operator"})


def adds_permissions(organization_role_code: str | None) -> bool:
    """Whether the tournament operator role adds anything to an organization role."""

    return organization_role_code not in OPERATING_ORGANIZATION_ROLES


def audit_payload(organization_user_id: UUID, role_code: str = TOURNAMENT_OPERATOR) -> dict[str, str]:
    if role_code not in TOURNAMENT_ROLE_CODES:
        raise ValueError(f"Unknown tournament role: {role_code}")
    return {"organization_user_id": str(organization_user_id), "role_code": role_code}
