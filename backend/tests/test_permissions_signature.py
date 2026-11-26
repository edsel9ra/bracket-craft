"""Authorization model: organization RBAC plus the per-match official scope.

RF-007/RF-008: ``require_permission`` and ``require_administrative_resolution``
must not accept a tournament scope anymore. The effective model is RBAC by
organization (``roles``/``organization_user_roles``) with an optional smaller
scope by match (``match_officials``).

The file also guards the source tree so a later change cannot reintroduce the
retired parameter in the application or in a test double.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.permissions import require_administrative_resolution, require_permission

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
TESTS_DIR = BACKEND_DIR / "tests"


@dataclass(frozen=True)
class _Context:
    organization_id: object
    organization_user_id: object


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RecordingSession:
    """Minimal AsyncSession double that records the statement and parameters."""

    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return _Result(1 if self.allowed else None)


def _context():
    return _Context(organization_id=uuid4(), organization_user_id=uuid4())


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def test_require_permission_has_no_tournament_scope():
    parameters = inspect.signature(require_permission).parameters
    assert "tournament_id" not in parameters
    assert list(parameters) == [
        "db",
        "context",
        "permission",
        "match_id",
        "role_codes",
    ]


def test_require_administrative_resolution_has_no_tournament_scope():
    parameters = inspect.signature(require_administrative_resolution).parameters
    assert "tournament_id" not in parameters
    assert list(parameters) == ["db", "context", "match_id"]


# ---------------------------------------------------------------------------
# Organization behavior is unchanged and match scope still travels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permission_resolves_by_organization_and_permission():
    session = _RecordingSession(allowed=True)
    context = _context()

    await require_permission(session, context, "MANAGE_TOURNAMENTS")

    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "FROM roles r" in sql
    assert "JOIN organization_user_roles our" in sql
    assert "our.organization_id = :organization_id" in sql
    assert "our.organization_user_id = :organization_user_id" in sql
    assert "tournament" not in sql.lower()
    assert params == {
        "organization_id": str(context.organization_id),
        "organization_user_id": str(context.organization_user_id),
        "permission": '["MANAGE_TOURNAMENTS"]',
        "match_id": None,
        "role_codes": None,
    }


@pytest.mark.asyncio
async def test_permission_denial_keeps_the_same_error():
    session = _RecordingSession(allowed=False)

    with pytest.raises(PermissionError, match="Permiso requerido: MANAGE_TOURNAMENTS"):
        await require_permission(session, _context(), "MANAGE_TOURNAMENTS")


@pytest.mark.asyncio
async def test_permission_passes_the_match_scope_and_role_codes():
    session = _RecordingSession(allowed=True)
    match_id = uuid4()

    await require_permission(
        session,
        _context(),
        "CLOSE_MATCH_REPORT",
        match_id=match_id,
        role_codes=("owner", "referee"),
    )

    sql, params = session.calls[0]
    assert "match_officials" in sql
    assert params["match_id"] == str(match_id)
    assert params["role_codes"] == ["owner", "referee"]
    assert "tournament_id" not in params


@pytest.mark.asyncio
async def test_administrative_resolution_only_needs_the_match():
    session = _RecordingSession(allowed=True)
    match_id = uuid4()

    await require_administrative_resolution(session, _context(), match_id)

    _, params = session.calls[0]
    assert params["permission"] == '["RESOLVE_MATCH_ADMINISTRATIVELY"]'
    assert params["match_id"] == str(match_id)
    assert params["role_codes"] == ["owner", "administrator"]
    assert "tournament_id" not in params


# ---------------------------------------------------------------------------
# Source guards: no caller or double reintroduces the retired scope
# ---------------------------------------------------------------------------


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _called_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


@pytest.mark.parametrize("directory", [APP_DIR, TESTS_DIR], ids=["app", "tests"])
def test_no_call_passes_tournament_id_to_the_permission_helpers(directory):
    offenders = []
    for path in _python_files(directory):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node) not in {
                "require_permission",
                "require_administrative_resolution",
            }:
                continue
            if any(keyword.arg == "tournament_id" for keyword in node.keywords):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")

    assert offenders == []


def test_permission_doubles_declare_the_new_signature():
    offenders = []
    for path in _python_files(TESTS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in {"permission", "allow", "deny"}:
                continue
            arguments = [argument.arg for argument in node.args.args]
            if "tournament_id" in arguments:
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")

    assert offenders == []


# ---------------------------------------------------------------------------
# Tournament operator branch (spec 049, plan D4)
# ---------------------------------------------------------------------------


class _SequenceSession(_RecordingSession):
    def __init__(self, *values):
        super().__init__()
        self.values = list(values)

    async def execute(self, query, params):
        self.calls.append((str(query), dict(params)))
        return _Result(self.values.pop(0))


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE", "CLOSE_MATCH_REPORT"])
async def test_match_permission_falls_back_to_the_tournament_operator(permission):
    session = _SequenceSession(None, True)
    context = _context()
    match_id = uuid4()

    await require_permission(session, context, permission, match_id=match_id)

    assert len(session.calls) == 2
    sql, params = session.calls[1]
    assert "tournament_operator_allows(" in sql
    assert params == {
        "organization_id": str(context.organization_id),
        "match_id": str(match_id),
        "permission": permission,
    }


@pytest.mark.asyncio
async def test_the_tournament_operator_fallback_keeps_the_same_error():
    session = _SequenceSession(None, False)

    with pytest.raises(PermissionError, match="Permiso requerido: CLOSE_MATCH_REPORT"):
        await require_permission(session, _context(), "CLOSE_MATCH_REPORT", match_id=uuid4())
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_an_organization_grant_does_not_query_the_tournament_role():
    session = _SequenceSession(1)

    await require_permission(session, _context(), "CLOSE_MATCH_REPORT", match_id=uuid4())

    assert len(session.calls) == 1
    assert "tournament_operator_allows" not in session.calls[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("permission", "match_id", "role_codes"),
    [
        ("CLOSE_MATCH_REPORT", None, None),
        ("MANAGE_TOURNAMENTS", uuid4(), None),
        ("RESOLVE_MATCH_ADMINISTRATIVELY", uuid4(), ("owner", "administrator")),
        ("CLOSE_MATCH_REPORT", uuid4(), ("owner", "referee")),
    ],
    ids=["sin-partido", "permiso-ajeno", "resolucion-administrativa", "con-roles"],
)
async def test_the_tournament_role_never_grants_outside_its_scope(permission, match_id, role_codes):
    session = _SequenceSession(None, True)

    with pytest.raises(PermissionError, match=f"Permiso requerido: {permission}"):
        await require_permission(session, _context(), permission, match_id=match_id, role_codes=role_codes)
    assert len(session.calls) == 1
    assert "tournament_operator_allows" not in session.calls[0][0]


@pytest.mark.asyncio
async def test_administrative_resolution_never_uses_the_tournament_role():
    session = _SequenceSession(None, True)

    with pytest.raises(PermissionError, match="RESOLVE_MATCH_ADMINISTRATIVELY"):
        await require_administrative_resolution(session, _context(), uuid4())
    assert len(session.calls) == 1
