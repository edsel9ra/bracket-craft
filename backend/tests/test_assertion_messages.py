"""Comprobaciones del apoyo de mensajes de fallo de la suite (spec 011, RF-004).

Los mensajes de fallo identifican la prueba, el estado HTTP y, cuando existe, el
identificador de motivo. Nunca incluyen el cuerpo de la respuesta, el enlace de
invitación ni el token. Las tres comprobaciones de contenido sobre
``response.text`` no son mensajes de fallo y se conservan intactas.
"""

import ast
from pathlib import Path

import httpx
import pytest

import assertion_messages
from assertion_messages import describe_response, describe_status, reason_code

TESTS_DIR = Path(__file__).resolve().parent
INVITATIONS_SUITE = TESTS_DIR / "test_invitations.py"
CONTENT_CHECK_STRINGS = ("access_token", "token_type", "invite_url")
BODY_ATTRIBUTES = frozenset({"text", "content"})
SENSITIVE_IDENTIFIERS = ("token", "invite_url")


def _request(
    method: str = "POST", path: str = "/api/v1/organizations/invitations"
) -> httpx.Request:
    return httpx.Request(method, f"http://test{path}")


def _response(
    status_code: int = 409,
    *,
    payload: dict | None = None,
    body: str = "",
    request: httpx.Request | None = None,
) -> httpx.Response:
    request = request or _request()
    if payload is not None:
        return httpx.Response(status_code, json=payload, request=request)
    return httpx.Response(status_code, text=body, request=request)


def test_describe_status_without_a_reason_code() -> None:
    assert describe_status("create invitation", 201, None) == "create invitation: HTTP 201"


def test_describe_status_with_a_reason_code() -> None:
    assert (
        describe_status("create invitation", 409, "INVITATION_OTHER_PENDING")
        == "create invitation: HTTP 409 (code=INVITATION_OTHER_PENDING)"
    )


@pytest.mark.parametrize(
    "code",
    [None, "", "   ", 409, ["INVITATION_OTHER_PENDING"], {"code": "x"}],
)
def test_describe_status_ignores_a_code_outside_the_allow_list(code) -> None:
    assert describe_status("reopen", 409, code) == "reopen: HTTP 409"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"code": "INVITATION_REVOKED_RESEND", "detail": "texto de diagnóstico"},
            "INVITATION_REVOKED_RESEND",
        ),
        ({"code": 409}, None),
        ({"code": ""}, None),
        ({"code": "   "}, None),
        ({"detail": "sin código"}, None),
        ({"code": {"nested": True}}, None),
        ("no-es-un-objeto", None),
        (None, None),
    ],
)
def test_reason_code_uses_only_the_allow_listed_key(payload, expected) -> None:
    assert reason_code(payload) == expected


def test_describe_response_never_includes_the_body_the_invite_url_or_the_token() -> None:
    token = "reopen-secret-token-0123456789abcdef"
    response = _response(
        409,
        payload={
            "code": "INVITATION_OTHER_PENDING",
            "detail": f"Ya existe una invitación pendiente: http://localhost/invitations/{token}",
            "invite_url": f"http://localhost/invitations/{token}",
            "token": token,
        },
    )

    message = describe_response("reopen a revoked invitation", response)

    assert message == (
        "reopen a revoked invitation: HTTP 409 (code=INVITATION_OTHER_PENDING)"
    )
    assert "invite_url" not in message
    assert token not in message
    assert "Ya existe" not in message


def test_describe_response_with_a_non_json_body_only_reports_the_status() -> None:
    response = _response(
        502, body="el servidor SMTP no está disponible: token=secreto-abc"
    )

    message = describe_response("reopen with a failing email", response)

    assert message == "reopen with a failing email: HTTP 502"
    assert "secreto-abc" not in message
    assert "SMTP" not in message


def test_describe_response_ignores_a_code_outside_the_allow_list() -> None:
    response = _response(410, payload={"code": 410, "invite_url": "http://x/y"})

    assert describe_response("accept an expired invitation", response) == (
        "accept an expired invitation: HTTP 410"
    )


def test_the_formatter_lives_in_the_test_support_code() -> None:
    assert Path(assertion_messages.__file__).resolve().parent == TESTS_DIR
    assert not (TESTS_DIR.parent / "app" / "assertion_messages.py").exists()


def _is_sensitive_identifier(name: str) -> bool:
    lowered = name.lower()
    return any(stem in lowered for stem in SENSITIVE_IDENTIFIERS)


def _message_references_body(message: ast.expr) -> bool:
    for node in ast.walk(message):
        if isinstance(node, ast.Attribute):
            if node.attr in BODY_ATTRIBUTES or _is_sensitive_identifier(node.attr):
                return True
            if node.attr == "json":
                return True
        if isinstance(node, ast.Name) and _is_sensitive_identifier(node.id):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "invite_url" in node.value:
                return True
    return False


def _forbidden_assertion_messages(source: str) -> list[str]:
    """Devuelve los mensajes de ``assert`` construidos desde el cuerpo o sus secretos."""

    findings: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert) or node.msg is None:
            continue
        if _message_references_body(node.msg):
            findings.append(ast.get_source_segment(source, node) or ast.unparse(node))
    return findings


def _content_checks(source: str) -> list[str]:
    """Devuelve las comprobaciones de contenido ``<literal> not in <x>.text``."""

    checks: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert) or node.msg is not None:
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.NotIn)
            and len(test.comparators) == 1
            and isinstance(test.left, ast.Constant)
            and isinstance(test.left.value, str)
            and test.left.value in CONTENT_CHECK_STRINGS
            and isinstance(test.comparators[0], ast.Attribute)
            and test.comparators[0].attr == "text"
        ):
            checks.append(test.left.value)
    return checks


def test_the_invitations_suite_has_no_failure_message_built_from_the_body() -> None:
    source = INVITATIONS_SUITE.read_text(encoding="utf-8")

    assert _forbidden_assertion_messages(source) == []


def test_the_invitations_suite_keeps_exactly_the_three_content_checks() -> None:
    checks = _content_checks(INVITATIONS_SUITE.read_text(encoding="utf-8"))

    assert len(checks) == 3
    assert sorted(checks) == sorted(CONTENT_CHECK_STRINGS)


def test_every_status_assertion_of_the_invitations_suite_uses_the_formatter() -> None:
    tree = ast.parse(INVITATIONS_SUITE.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "describe_response"
    ]

    assert len(calls) == 40


def test_the_sweep_detects_an_injected_forbidden_message() -> None:
    source = (
        "def test_sample(response, token):\n"
        "    assert response.status_code == 200, response.text\n"
        '    assert response.status_code == 201, f"create: {response.json()}"\n'
        '    assert response.status_code == 202, f"accept: {token}"\n'
        "    assert response.status_code == 203, response.content\n"
        '    assert response.status_code == 204, f"invite_url={invite_url}"\n'
        '    assert "access_token" not in response.text\n'
    )

    assert len(_forbidden_assertion_messages(source)) == 5
    assert _content_checks(source) == ["access_token"]
