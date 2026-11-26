"""Catálogo del rol por torneo (spec 049, RF-001, RF-001a, RF-003b; plan D2 y D8)."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.tournament_roles.catalog import (
    TOURNAMENT_OPERATOR,
    TOURNAMENT_OPERATOR_PERMISSIONS,
    TOURNAMENT_ROLE_CODES,
    adds_permissions,
    audit_payload,
)

MIGRATION = Path(__file__).resolve().parents[2] / "infra/postgres/migrations/069_tournament_roles.sql"


def _function_body() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    start = sql.index("FUNCTION public.tournament_operator_allows")
    return sql[start:sql.index("$$;", start)]


def test_the_only_tournament_role_is_the_operator():
    assert TOURNAMENT_OPERATOR == "tournament_operator"
    assert TOURNAMENT_ROLE_CODES == ("tournament_operator",)


def test_operator_permissions_are_the_three_match_permissions():
    assert TOURNAMENT_OPERATOR_PERMISSIONS == frozenset(
        {"VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE", "CLOSE_MATCH_REPORT"}
    )
    assert isinstance(TOURNAMENT_OPERATOR_PERMISSIONS, frozenset)


def test_python_permissions_mirror_the_sql_function():
    listed = re.search(r"p_permission IN \(([^)]*)\)", _function_body())
    assert listed is not None
    assert frozenset(re.findall(r"'([A-Z_]+)'", listed.group(1))) == TOURNAMENT_OPERATOR_PERMISSIONS


def test_python_role_codes_mirror_the_sql_check_and_function():
    sql = MIGRATION.read_text(encoding="utf-8")
    check = re.search(r"CHECK \(role_code IN \(([^)]*)\)\)", sql)
    assert check is not None
    assert tuple(re.findall(r"'([a-z_]+)'", check.group(1))) == TOURNAMENT_ROLE_CODES
    assert f"t.role_code = '{TOURNAMENT_OPERATOR}'" in _function_body()


@pytest.mark.parametrize("code", ["owner", "administrator", "operator"])
def test_operating_organization_roles_gain_nothing(code):
    assert adds_permissions(code) is False


@pytest.mark.parametrize("code", ["referee", "viewer", "custom", None])
def test_other_organization_roles_gain_the_operation(code):
    assert adds_permissions(code) is True


def test_audit_payload_only_carries_the_member_and_the_role():
    member = uuid4()
    assert audit_payload(member) == {"organization_user_id": str(member), "role_code": "tournament_operator"}
    assert audit_payload(member, TOURNAMENT_OPERATOR) == audit_payload(member)


def test_audit_payload_rejects_an_unknown_role():
    with pytest.raises(ValueError):
        audit_payload(uuid4(), "tournament_admin")
