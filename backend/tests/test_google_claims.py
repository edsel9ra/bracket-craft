"""Destino de retorno, nombre para mostrar y prueba de identidad de Google
(RF-5, RF-8, RF-9, RF-12, RNF-4).

Todas las piezas son puras: no leen reloj, entorno, red ni base de datos, y
``validate_return_destination``/``sanitize_display_name`` no lanzan.
``validate_return_destination`` aplica RF-9 (solo rutas internas relativas, sin
host ni esquema, hasta 512 caracteres; si no es válida, el llamador usa el
destino por defecto). ``sanitize_display_name`` aplica RF-12 (recorte a 100
caracteres, reserva con la parte local del correo y nombre neutro estable; el
alta nunca falla por el nombre). ``parse_identity_claims`` aplica RF-5, RF-8 y
RNF-4 sobre la respuesta del canje: tamaño, JSON, ``id_token``, emisor,
audiencia, vigencia frente al ``now`` inyectado, sujeto, correo y correo
verificado; la firma no se verifica (D-9) porque el token llega del endpoint de
token por TLS autenticado con el secreto del cliente.
"""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from app.modules.identity.google_claims import (
    DEFAULT_DISPLAY_NAME,
    GOOGLE_ISSUERS,
    MAX_DISPLAY_NAME_LENGTH,
    MAX_IDENTITY_RESPONSE_BYTES,
    MAX_RETURN_DESTINATION_LENGTH,
    GoogleIdentity,
    GoogleIdentityInvalid,
    parse_identity_claims,
    sanitize_display_name,
    validate_return_destination,
)


# ---------------------------------------------------------------------------
# Prueba de identidad: respuesta del canje y ``id_token``
# ---------------------------------------------------------------------------

CLIENT_ID = "bracket-craft-client.apps.googleusercontent.com"

# Instante fijo del intento. El reloj real no interviene: la vigencia se
# decide solo con este valor inyectado.
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
EXP_SECONDS = int(NOW.timestamp()) + 600


def encode_segment(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def id_token(payload: dict, *, header: dict | None = None) -> str:
    """Build a three-segment token with an empty signature (D-9)."""

    header = header or {"alg": "RS256", "typ": "JWT"}
    return f"{encode_segment(header)}.{encode_segment(payload)}."


def token_response(
    payload: dict,
    *,
    extra: dict | None = None,
    token: str | None = None,
) -> bytes:
    body = {"access_token": "provider-access-token", "token_type": "Bearer"}
    body["id_token"] = token if token is not None else id_token(payload)
    body.update(extra or {})
    return json.dumps(body).encode("utf-8")


def valid_payload(**overrides) -> dict:
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": EXP_SECONDS,
        "sub": "google-subject-123",
        "email": "ana@example.test",
        "email_verified": True,
        "name": "Ana Pérez",
    }
    payload.update(overrides)
    return payload


def payload_without(*keys: str, **overrides) -> dict:
    payload = valid_payload(**overrides)
    for key in keys:
        payload.pop(key, None)
    return payload



# ---------------------------------------------------------------------------
# Prueba de identidad: casos válidos
# ---------------------------------------------------------------------------


def test_parse_identity_claims_accepts_a_complete_response():
    identity = parse_identity_claims(
        token_response(valid_payload()), client_id=CLIENT_ID, now=NOW
    )

    assert identity == GoogleIdentity(
        subject="google-subject-123",
        email="ana@example.test",
        email_verified=True,
        name="Ana Pérez",
    )


def test_parse_identity_claims_accepts_the_unprefixed_google_issuer():
    raw = token_response(valid_payload(iss="accounts.google.com"))

    identity = parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)

    assert identity.subject == "google-subject-123"


def test_parse_identity_claims_defaults_to_the_documented_issuers():
    assert GOOGLE_ISSUERS == frozenset(
        {"https://accounts.google.com", "accounts.google.com"}
    )


def test_parse_identity_claims_accepts_a_name_absent():
    payload = valid_payload()
    del payload["name"]

    identity = parse_identity_claims(
        token_response(payload), client_id=CLIENT_ID, now=NOW
    )

    assert identity.name is None


def test_parse_identity_claims_treats_a_non_string_name_as_absent():
    identity = parse_identity_claims(
        token_response(valid_payload(name={"first": "Ana"})),
        client_id=CLIENT_ID,
        now=NOW,
    )

    assert identity.name is None


def test_parse_identity_claims_discards_every_other_claim():
    raw = token_response(
        valid_payload(
            picture="https://lh3.example.test/photo.jpg",
            locale="es-AR",
            given_name="Ana",
            family_name="Pérez",
            hd="example.test",
            azp=CLIENT_ID,
            iat=int(NOW.timestamp()),
        )
    )

    identity = parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)

    assert [field.name for field in fields(identity)] == [
        "subject",
        "email",
        "email_verified",
        "name",
    ]
    assert identity.subject == "google-subject-123"
    assert identity.email == "ana@example.test"


def test_parse_identity_claims_accepts_a_string_body():
    raw = token_response(valid_payload()).decode("utf-8")

    identity = parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)

    assert identity.subject == "google-subject-123"


def test_parse_identity_claims_accepts_a_custom_issuer_set():
    raw = token_response(valid_payload(iss="https://issuer.example.test"))

    identity = parse_identity_claims(
        raw,
        client_id=CLIENT_ID,
        now=NOW,
        issuers=frozenset({"https://issuer.example.test"}),
    )

    assert identity.subject == "google-subject-123"


def test_google_identity_is_immutable():
    identity = GoogleIdentity(
        subject="google-subject-123",
        email="ana@example.test",
        email_verified=True,
        name=None,
    )

    with pytest.raises(FrozenInstanceError):
        identity.subject = "other"


# ---------------------------------------------------------------------------
# Prueba de identidad: tamaño, JSON e ``id_token``
# ---------------------------------------------------------------------------


def test_parse_identity_claims_rejects_more_than_8_kib():
    raw = token_response(valid_payload(), extra={"padding": "x" * 9000})

    assert len(raw) > MAX_IDENTITY_RESPONSE_BYTES
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)


def test_parse_identity_claims_checks_the_size_before_decoding_the_body():
    raw = token_response(valid_payload())

    # The body is valid, but the size budget is smaller than the payload: the
    # size check runs first and rejects without parsing.
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            raw, client_id=CLIENT_ID, now=NOW, max_bytes=len(raw) - 1
        )
    assert (
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW, max_bytes=len(raw))
        .subject
        == "google-subject-123"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"{not json",
        b"",
        b"null",
        b"[]",
        b'"text"',
        b'{"id_token": 123}',
        b'{"id_token": ""}',
        b'{"access_token": "only"}',
        b"\xff\xfe\x00",
    ],
)
def test_parse_identity_claims_rejects_invalid_bodies(raw):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "only.two",
        "a.b.c.d",
        f"{encode_segment({'alg': 'RS256'})}.%%%.",
        f"{encode_segment({'alg': 'RS256'})}.{encode_segment({'sub': 'x'})}.sig",
    ],
)
def test_parse_identity_claims_rejects_malformed_tokens(token):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response({}, token=token), client_id=CLIENT_ID, now=NOW
        )


# ---------------------------------------------------------------------------
# Prueba de identidad: emisor, audiencia y vigencia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        valid_payload(iss="https://evil.test"),
        valid_payload(iss=""),
        valid_payload(iss=None),
        payload_without("iss"),
    ],
)
def test_parse_identity_claims_rejects_a_foreign_or_missing_issuer(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


@pytest.mark.parametrize(
    "payload",
    [
        valid_payload(aud="another-client.apps.googleusercontent.com"),
        valid_payload(aud=""),
        valid_payload(aud=None),
        payload_without("aud"),
    ],
)
def test_parse_identity_claims_rejects_a_foreign_or_missing_audience(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


def test_parse_identity_claims_requires_aud_to_be_the_client_id_exactly():
    # ``aud`` may be an array in OIDC, but the plan fixes strict equality; a
    # list is rejected instead of guessed.
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(valid_payload(aud=[CLIENT_ID])),
            client_id=CLIENT_ID,
            now=NOW,
        )


def test_parse_identity_claims_accepts_a_token_that_is_still_valid_for_now():
    # ``exp`` is in the past for the real clock (2026-01-01) but still in the
    # future for the injected ``now``: only the parameter decides.
    raw = token_response(valid_payload(exp=EXP_SECONDS))

    assert int(NOW.timestamp()) < EXP_SECONDS
    assert (
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW).subject
        == "google-subject-123"
    )


@pytest.mark.parametrize(
    "payload",
    [
        payload_without("exp"),
        valid_payload(exp=int(NOW.timestamp()) - 1),
        valid_payload(exp=int(NOW.timestamp())),
        valid_payload(exp="9999999999"),
        valid_payload(exp=None),
        valid_payload(exp=True),
        valid_payload(exp=float("nan")),
        valid_payload(exp=float("inf")),
    ],
)
def test_parse_identity_claims_rejects_an_expired_or_invalid_expiry(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


def test_parse_identity_claims_uses_the_injected_now_not_the_system_clock():
    raw = token_response(valid_payload(exp=EXP_SECONDS))
    later = datetime.fromtimestamp(EXP_SECONDS + 1, tz=UTC)

    assert (
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW).subject
        == "google-subject-123"
    )
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(raw, client_id=CLIENT_ID, now=later)


# ---------------------------------------------------------------------------
# Prueba de identidad: sujeto, correo y correo verificado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        valid_payload(sub=""),
        valid_payload(sub="   "),
        valid_payload(sub=None),
        valid_payload(sub=123),
        valid_payload(sub="s" * 256),
        payload_without("sub"),
    ],
)
def test_parse_identity_claims_rejects_a_missing_or_invalid_subject(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


def test_parse_identity_claims_accepts_a_subject_of_255_characters():
    subject = "s" * 255

    identity = parse_identity_claims(
        token_response(valid_payload(sub=subject)), client_id=CLIENT_ID, now=NOW
    )

    assert identity.subject == subject


@pytest.mark.parametrize(
    "payload",
    [
        valid_payload(email=""),
        valid_payload(email="   "),
        valid_payload(email=None),
        valid_payload(email=123),
        valid_payload(email="a" * 250 + "@example.test"),
        payload_without("email"),
    ],
)
def test_parse_identity_claims_rejects_a_missing_or_invalid_email(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


def test_parse_identity_claims_accepts_an_email_of_255_characters():
    email = f"{'a' * 242}@example.test"

    identity = parse_identity_claims(
        token_response(valid_payload(email=email)), client_id=CLIENT_ID, now=NOW
    )

    assert len(email) == 255
    assert identity.email == email


@pytest.mark.parametrize(
    "payload",
    [
        valid_payload(email_verified=False),
        valid_payload(email_verified="true"),
        valid_payload(email_verified=1),
        valid_payload(email_verified=None),
        payload_without("email_verified"),
    ],
)
def test_parse_identity_claims_rejects_an_unverified_email(payload):
    with pytest.raises(GoogleIdentityInvalid):
        parse_identity_claims(
            token_response(payload), client_id=CLIENT_ID, now=NOW
        )


def test_parse_identity_claims_does_not_leak_claims_in_the_error():
    raw = token_response(
        valid_payload(
            iss="https://evil.test",
            sub="secret-subject-value",
            email="secret-email@example.test",
        )
    )

    with pytest.raises(GoogleIdentityInvalid) as error:
        parse_identity_claims(raw, client_id=CLIENT_ID, now=NOW)

    message = str(error.value)
    assert "secret-subject-value" not in message
    assert "secret-email@example.test" not in message
    assert id_token(valid_payload()) not in message



# ---------------------------------------------------------------------------
# Destino de retorno: rutas internas aceptadas tal cual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/workspace",
        "/organization",
        "/workspace/tournaments/00000000-0000-0000-0000-000000000001",
        "/invitations/abc123?token=xyz",
        "/workspace/tournaments/1?stage=abc#equipos",
        "/%20solo-un-espacio-codificado",
    ],
)
def test_validate_return_destination_accepts_internal_paths(value):
    assert validate_return_destination(value) == value


def test_validate_return_destination_does_not_rewrite_the_value():
    value = "/invitations/a%20b?token=xyz"

    destination = validate_return_destination(value)

    # The encoded value is validated but returned untouched: the caller stores
    # it as a path, never as a decoded URL.
    assert destination == value


def test_validate_return_destination_accepts_exactly_max_length():
    value = "/" + "a" * (MAX_RETURN_DESTINATION_LENGTH - 1)

    assert len(value) == MAX_RETURN_DESTINATION_LENGTH
    assert validate_return_destination(value) == value


def test_validate_return_destination_uses_the_injected_max_length():
    assert validate_return_destination("/123456789", max_length=10) == "/123456789"
    assert validate_return_destination("/1234567890", max_length=10) is None


# ---------------------------------------------------------------------------
# Destino de retorno: fuera de origen, esquema, host o valores no válidos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        "   ",
        "workspace",
        "/workspace".replace("/", "", 1),
        "//evil.test",
        "///evil.test",
        "//evil.test/workspace",
        "http://evil.test",
        "https://evil.test/workspace",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://evil.test",
        "/\\evil.test",
        "\\\\evil.test",
        "/workspace\\..\\evil",
        "/workspace\n",
        "/workspace\r\nLocation: https://evil.test",
        "/workspace\t",
        "/workspace\x00",
        "/workspace\x7f",
        "/workspace\x85",
        # Un salto de codificación no basta para colarse como host, esquema,
        # barra invertida o carácter de control.
        "/%2F%2Fevil.test",
        "/%5Cevil.test",
        "/workspace%0ALocation:%20https://evil.test",
        "/%68%74%74%70%3A%2F%2Fevil.test",
    ],
)
def test_validate_return_destination_rejects_unsafe_values(value):
    assert validate_return_destination(value) is None


@pytest.mark.parametrize("value", [123, 1.5, True, b"/workspace", ["/workspace"], object()])
def test_validate_return_destination_rejects_non_strings(value):
    assert validate_return_destination(value) is None


def test_validate_return_destination_rejects_too_long_values():
    value = "/" + "a" * MAX_RETURN_DESTINATION_LENGTH

    assert len(value) == MAX_RETURN_DESTINATION_LENGTH + 1
    assert validate_return_destination(value) is None
    # Exactly 512 characters is the accepted boundary (proven above); one more
    # character is rejected instead of truncated.
    assert validate_return_destination(value[:MAX_RETURN_DESTINATION_LENGTH]) is not None


def test_validate_return_destination_rejects_encoded_host_after_one_decode():
    encoded = "/%2F%2Fevil.test"

    assert validate_return_destination(encoded) is None
    # The rejection is not a blanket ban on percent signs inside a path.
    assert validate_return_destination("/informe%2F2026") == "/informe%2F2026"


# ---------------------------------------------------------------------------
# Nombre para mostrar: recorte y reservas de RF-12
# ---------------------------------------------------------------------------


def test_sanitize_display_name_trims_the_provider_name():
    assert sanitize_display_name("  Ana Pérez  ", "ana@example.test") == "Ana Pérez"


def test_sanitize_display_name_truncates_to_100_characters():
    name = "A" * (MAX_DISPLAY_NAME_LENGTH + 50)

    sanitized = sanitize_display_name(name, "ana@example.test")

    assert sanitized == "A" * MAX_DISPLAY_NAME_LENGTH
    assert len(sanitized) == 100


def test_sanitize_display_name_keeps_exactly_100_characters():
    name = "B" * MAX_DISPLAY_NAME_LENGTH

    assert sanitize_display_name(name, "ana@example.test") == name


def test_sanitize_display_name_trims_before_truncating():
    name = "  " + "C" * MAX_DISPLAY_NAME_LENGTH + "  "

    assert sanitize_display_name(name, "ana@example.test") == "C" * MAX_DISPLAY_NAME_LENGTH


@pytest.mark.parametrize("name", [None, "", " ", "   ", "\t\n"])
def test_sanitize_display_name_falls_back_to_the_email_local_part(name):
    assert sanitize_display_name(name, "  ana.perez@example.test  ") == "ana.perez"


def test_sanitize_display_name_truncates_the_local_part_to_100_characters():
    local_part = "d" * (MAX_DISPLAY_NAME_LENGTH + 20)

    sanitized = sanitize_display_name(None, f"{local_part}@example.test")

    assert sanitized == local_part[:MAX_DISPLAY_NAME_LENGTH]


def test_sanitize_display_name_treats_a_missing_at_sign_as_the_local_part():
    assert sanitize_display_name("", "ana.perez") == "ana.perez"


@pytest.mark.parametrize(
    ("name", "email"),
    [
        (None, "@example.test"),
        ("   ", "@example.test"),
        (None, "   @example.test"),
        (None, ""),
        (None, "   "),
        (None, None),
        (123, "ana@example.test"),
    ],
)
def test_sanitize_display_name_never_raises_and_falls_back_to_the_neutral_name(
    name, email
):
    assert sanitize_display_name(name, email)


def test_sanitize_display_name_uses_the_stable_neutral_name():
    assert sanitize_display_name(None, "@example.test") == DEFAULT_DISPLAY_NAME
    assert sanitize_display_name("   ", "@example.test") == DEFAULT_DISPLAY_NAME
    assert DEFAULT_DISPLAY_NAME == "Cuenta de Bracket Craft"


@pytest.mark.parametrize("name", [None, "", "   ", 123, object()])
def test_sanitize_display_name_always_returns_a_non_empty_string(name):
    result = sanitize_display_name(name, "ana@example.test")

    assert isinstance(result, str)
    assert result.strip() != ""
