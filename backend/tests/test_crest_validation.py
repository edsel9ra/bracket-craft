"""Error catalog, safe object keys and declared content validation for crests.

The catalog is closed: the eight codes of the specification always travel as a
string ``detail`` (the Spanish fallback a client shows when it ignores ``code``)
plus the additive ``code`` the frontend translates. The object key is pure and
never depends on the clock or on the file name chosen by the person: the caller
passes the extension derived from the detected content and the random token is
generated inside (it can be injected to keep the test deterministic).

Content validation works on hand-built containers: it reads the signature, walks
the PNG/WEBP chunk headers and never decodes, re-encodes or trusts a file name.
Truncated or unreadable containers are accepted and the declared risk is that
animation or corruption that only shows when decoding is not detected.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from fastapi import HTTPException, status

from app.core.storage import _is_valid_key
from app.modules.crests.errors import (
    CREST_ANIMATION_UNSUPPORTED,
    CREST_ERROR_DETAILS,
    CREST_ERROR_STATUS,
    CREST_FILE_EMPTY,
    CREST_FORBIDDEN,
    CREST_FORMAT_UNSUPPORTED,
    CREST_NOT_FOUND,
    CREST_STORAGE_UNAVAILABLE,
    CREST_TOO_LARGE,
    CREST_UPLOAD_FAILED,
    CrestError,
    crest_error_body,
)
from app.modules.crests.validation import (
    ALLOWED_CREST_EXTENSIONS,
    CrestFile,
    crest_object_key,
    detect_image_type,
    png_declares_animation,
    validate_crest_content,
    webp_declares_animation,
)

ORG = "0a000000-0000-4000-8000-000000000001"
TOURNAMENT = "0a000000-0000-4000-8000-000000000010"
TEAM = "0a000000-0000-4000-8000-000000000020"
TOKEN = "0a000000-0000-4000-8000-0000000000aa"

#: The closed catalog of the specification: code, HTTP status and the exact
#: Spanish string kept as ``detail`` for clients that ignore ``code``.
CATALOG = (
    (CREST_FILE_EMPTY, status.HTTP_422_UNPROCESSABLE_CONTENT, "El archivo está vacío"),
    (
        CREST_FORMAT_UNSUPPORTED,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "El escudo debe ser una imagen JPG, PNG o WEBP",
    ),
    (
        CREST_ANIMATION_UNSUPPORTED,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "El escudo no puede ser una imagen animada",
    ),
    (
        CREST_TOO_LARGE,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "El escudo supera el tamaño máximo permitido",
    ),
    (CREST_NOT_FOUND, status.HTTP_404_NOT_FOUND, "El equipo no fue encontrado"),
    (
        CREST_FORBIDDEN,
        status.HTTP_403_FORBIDDEN,
        "No tienes permiso para gestionar el escudo de este equipo",
    ),
    (
        CREST_STORAGE_UNAVAILABLE,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "El almacenamiento de imágenes no está disponible",
    ),
    (
        CREST_UPLOAD_FAILED,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "No se pudo completar la operación del escudo",
    ),
)


# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------


def test_crest_error_catalog_has_the_eight_codes_of_the_specification():
    assert set(CREST_ERROR_STATUS) == {code for code, _status, _detail in CATALOG}
    assert set(CREST_ERROR_DETAILS) == set(CREST_ERROR_STATUS)
    for code, expected_status, expected_detail in CATALOG:
        assert CREST_ERROR_STATUS[code] == expected_status
        assert CREST_ERROR_DETAILS[code] == expected_detail


@pytest.mark.parametrize(
    ("code", "expected_status", "expected_detail"),
    CATALOG,
    ids=[code for code, _status, _detail in CATALOG],
)
def test_crest_error_serializes_a_string_detail_plus_the_additive_code(
    code, expected_status, expected_detail
):
    error = CrestError(code)

    assert isinstance(error, HTTPException)
    assert error.status_code == expected_status
    assert error.code == code
    assert isinstance(error.detail, str)
    assert error.detail == expected_detail

    body = crest_error_body(error)
    assert body == {"detail": expected_detail, "code": code}
    assert set(body) == {"detail", "code"}
    # The body is a plain JSON object: no internal reference, no file name and
    # no path ever travels inside it.
    assert json.loads(json.dumps(body)) == body
    assert "/" not in body["detail"]
    assert ".." not in body["detail"]
    assert "private/" not in body["detail"]


@pytest.mark.parametrize(
    ("code", "_status", "_detail"),
    CATALOG,
    ids=[code for code, _status, _detail in CATALOG],
)
def test_crest_error_detail_is_always_a_string(code, _status, _detail):
    # A caller may explain the concrete case, but ``detail`` never stops being a
    # string and ``code`` never changes language.
    error = CrestError(code, detail="Detalle concreto del rechazo")
    assert error.detail == "Detalle concreto del rechazo"
    assert isinstance(error.detail, str)
    assert error.code == code
    assert crest_error_body(error) == {
        "detail": "Detalle concreto del rechazo",
        "code": code,
    }


# ---------------------------------------------------------------------------
# Safe object keys
# ---------------------------------------------------------------------------


def test_crest_object_key_layout_carries_org_tournament_team_and_a_random_token():
    key = crest_object_key(ORG, TOURNAMENT, TEAM, ".webp")
    prefix = f"private/organizations/{ORG}/tournaments/{TOURNAMENT}/teams/{TEAM}/"
    assert key.startswith(prefix)

    filename = key.removeprefix(prefix)
    token, extension = filename.rsplit(".", 1)
    assert extension == "webp"
    assert str(UUID(token)) == token
    assert UUID(token).version == 4

    # Two calls never reuse the identifier: the key is not derived from the team
    # or from the clock.
    assert crest_object_key(ORG, TOURNAMENT, TEAM, ".webp") != key


def test_crest_object_key_is_valid_for_the_storage_guard():
    for extension in ALLOWED_CREST_EXTENSIONS:
        key = crest_object_key(ORG, TOURNAMENT, TEAM, extension)
        assert _is_valid_key(key) is True
        assert not key.startswith("/")
        assert ".." not in key.split("/")
        assert key.endswith(extension)


def test_crest_object_key_with_an_injected_token_is_exact_and_ignores_any_file_name():
    key = crest_object_key(ORG, TOURNAMENT, TEAM, ".jpg", token=TOKEN)

    assert (
        key
        == f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
        f"/teams/{TEAM}/{TOKEN}.jpg"
    )
    assert _is_valid_key(key) is True
    # No chosen name, no extra extension and no path of the original file.
    for name in (
        "escudo final del equipo.png",
        "Escudo.PNG",
        "../../etc/passwd",
        "logo.php",
        "crest.gif",
    ):
        assert name not in key
        assert name.lower() not in key.lower()
    assert key.count(".") == 1
    assert " " not in key


def test_crest_object_key_only_accepts_the_detected_extensions():
    for rejected in ("", ".gif", ".svg", ".php", "jpg", ".JPG", ".png/../x.php"):
        with pytest.raises(ValueError):
            crest_object_key(ORG, TOURNAMENT, TEAM, rejected)

    # The content type decides: the same team and organization get a different
    # key per detected extension, and the injected token is never reused.
    keys = {
        crest_object_key(ORG, TOURNAMENT, TEAM, extension, token=TOKEN)
        for extension in ALLOWED_CREST_EXTENSIONS
    }
    assert len(keys) == len(ALLOWED_CREST_EXTENSIONS)


@pytest.mark.parametrize("token", ("", "../escape", "with/slash", "with..dots"))
def test_crest_object_key_rejects_a_token_that_would_break_the_guard(token):
    with pytest.raises(ValueError):
        crest_object_key(ORG, TOURNAMENT, TEAM, ".png", token=token)


# ---------------------------------------------------------------------------
# Hand-built containers (no real images, no decoding)
# ---------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff;"
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
XML_BYTES = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
HTML_BYTES = b"<!DOCTYPE html><html><body>not an image</body></html>"

IHDR_DATA = b"\x00\x00\x00\x01" * 2 + b"\x08\x06\x00\x00\x00"


def png_chunk(kind: bytes, data: bytes = b"") -> bytes:
    """Build a PNG chunk; the CRC is not validated by the walker."""

    return len(data).to_bytes(4, "big") + kind + data + b"\x00\x00\x00\x00"


def png(*chunks: bytes) -> bytes:
    return PNG_SIGNATURE + b"".join(chunks)


def webp_chunk(fourcc: bytes, data: bytes = b"") -> bytes:
    """Build a RIFF chunk with its pad byte (WEBP requires even chunk sizes)."""

    chunk = fourcc + len(data).to_bytes(4, "little") + data
    if len(data) % 2:
        chunk += b"\x00"
    return chunk


def webp(*chunks: bytes) -> bytes:
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def webp_vp8x(flags: int) -> bytes:
    """VP8X payload: flags, three reserved bytes and a 3+3 byte canvas size."""

    return bytes([flags]) + b"\x00" * 3 + b"\x00\x00\x01" + b"\x00\x00\x01"


PNG_STATIC = png(
    png_chunk(b"IHDR", IHDR_DATA),
    png_chunk(b"IDAT", b"\x78\x9c\x03\x00"),
    png_chunk(b"IEND"),
)
PNG_APNG = png(
    png_chunk(b"IHDR", IHDR_DATA),
    png_chunk(b"acTL", b"\x00" * 8),
    png_chunk(b"IDAT", b"\x78\x9c\x03\x00"),
    png_chunk(b"IEND"),
)
PNG_ACTL_AFTER_IDAT = png(
    png_chunk(b"IHDR", IHDR_DATA),
    png_chunk(b"IDAT", b"\x78\x9c\x03\x00"),
    png_chunk(b"acTL", b"\x00" * 8),
)
PNG_ACTL_TRUNCATED = PNG_SIGNATURE + b"\x00\x00\x00\x99" + b"acTL" + b"\x00\x00"
PNG_TRUNCATED = PNG_SIGNATURE + b"\x00\x00\x00\x64" + b"tEXt" + b"\x00\x00"
PNG_SIGNATURE_ONLY = PNG_SIGNATURE + b"\x00\x00"

WEBP_STATIC = webp(
    webp_chunk(b"VP8X", webp_vp8x(0x00)), webp_chunk(b"VP8 ", b"\x00" * 10)
)
WEBP_ANIMATED_VP8X = webp(
    webp_chunk(b"VP8X", webp_vp8x(0x02)), webp_chunk(b"VP8 ", b"\x00" * 10)
)
WEBP_ANIM = webp(
    webp_chunk(b"VP8X", webp_vp8x(0x00)), webp_chunk(b"ANIM", b"\x00" * 6)
)
WEBP_TRUNCATED = (
    b"RIFF"
    + (20).to_bytes(4, "little")
    + b"WEBP"
    + b"VP8X"
    + (100).to_bytes(4, "little")
    + b"\x00"
)
WEBP_HEADER_ONLY = b"RIFF" + (4).to_bytes(4, "little") + b"WEBP"


# ---------------------------------------------------------------------------
# Type detection: the signature decides, never the file name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared_name", "content", "expected"),
    [
        ("escudo.png", JPEG_BYTES, ".jpg"),
        ("escudo.jpg", PNG_STATIC, ".png"),
        ("escudo.bin", WEBP_STATIC, ".webp"),
        ("escudo.jpeg", b"\xff\xd8\xff", ".jpg"),
        ("escudo.png", GIF_BYTES, None),
        ("escudo.png", SVG_BYTES, None),
        ("escudo.webp", XML_BYTES, None),
        ("escudo.jpg", HTML_BYTES, None),
        ("escudo.png", b"", None),
        ("escudo.webp", b"RIFF\x00\x00\x00\x00WAVE", None),
    ],
)
def test_detect_image_type_reads_the_content_not_the_file_name(
    declared_name, content, expected
):
    # The function never receives the name: this parameter exists only to make
    # the "the extension says .png" case explicit in the test.
    assert declared_name
    assert detect_image_type(content) == expected


# ---------------------------------------------------------------------------
# Admission: size, type, animation and the resulting extension
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared_name", "content", "extension", "content_type"),
    [
        ("escudo.png", JPEG_BYTES, ".jpg", "image/jpeg"),
        ("escudo.jpeg", PNG_STATIC, ".png", "image/png"),
        ("escudo.png", WEBP_STATIC, ".webp", "image/webp"),
    ],
)
def test_validate_crest_content_accepts_the_three_formats_with_the_detected_extension(
    declared_name, content, extension, content_type
):
    accepted = validate_crest_content(content, max_bytes=1024)

    assert isinstance(accepted, CrestFile)
    assert accepted.content == content
    assert accepted.extension == extension
    assert accepted.content_type == content_type
    # The declared name is not even an argument: the content decides, so a
    # ``.png`` name with JPEG bytes is accepted as JPEG.
    assert not declared_name.endswith(extension)


def test_validate_crest_content_rejects_empty_before_the_size_limit():
    with pytest.raises(CrestError) as error:
        validate_crest_content(b"", max_bytes=0)

    assert error.value.code == CREST_FILE_EMPTY
    assert error.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert isinstance(error.value.detail, str)


def test_validate_crest_content_uses_the_received_size_limit():
    assert (
        validate_crest_content(PNG_STATIC, max_bytes=len(PNG_STATIC)).extension
        == ".png"
    )

    with pytest.raises(CrestError) as error:
        validate_crest_content(PNG_STATIC + b"\x00", max_bytes=len(PNG_STATIC))

    assert error.value.code == CREST_TOO_LARGE
    assert error.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("declared_name", "content"),
    [
        ("escudo.png", GIF_BYTES),
        ("escudo.jpg", SVG_BYTES),
        ("escudo.webp", XML_BYTES),
        ("escudo.png", HTML_BYTES),
    ],
)
def test_validate_crest_content_rejects_the_content_although_the_name_says_png(
    declared_name, content
):
    assert declared_name
    with pytest.raises(CrestError) as error:
        validate_crest_content(content, max_bytes=1024)

    assert error.value.code == CREST_FORMAT_UNSUPPORTED
    assert error.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("content", "extension"),
    [
        (PNG_APNG, ".png"),
        (WEBP_ANIMATED_VP8X, ".webp"),
        (WEBP_ANIM, ".webp"),
    ],
)
def test_validate_crest_content_rejects_detectable_animation(content, extension):
    # ``extension`` documents which branch rejected it; the detected type is the
    # one that decides whether the animation walk runs.
    assert detect_image_type(content) == extension
    with pytest.raises(CrestError) as error:
        validate_crest_content(content, max_bytes=1024)

    assert error.value.code == CREST_ANIMATION_UNSUPPORTED
    assert error.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_validate_crest_content_accepts_actl_after_the_image_data():
    accepted = validate_crest_content(PNG_ACTL_AFTER_IDAT, max_bytes=1024)
    assert accepted.extension == ".png"
    assert accepted.content_type == "image/png"


@pytest.mark.parametrize(
    ("content", "extension"),
    [
        (PNG_TRUNCATED, ".png"),
        (PNG_SIGNATURE_ONLY, ".png"),
        (WEBP_TRUNCATED, ".webp"),
        (WEBP_HEADER_ONLY, ".webp"),
        (b"\xff\xd8\xff", ".jpg"),
    ],
)
def test_validate_crest_content_accepts_unreadable_or_truncated_containers(
    content, extension
):
    # Declared limit: a truncated or corrupt container that keeps an admitted
    # header is accepted and served; only the container marks are inspected.
    accepted = validate_crest_content(content, max_bytes=1024)
    assert accepted.extension == extension


# ---------------------------------------------------------------------------
# PNG animation marks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (PNG_STATIC, False),
        (PNG_APNG, True),
        (PNG_ACTL_AFTER_IDAT, False),
        (PNG_ACTL_TRUNCATED, True),
        (PNG_TRUNCATED, False),
        (PNG_SIGNATURE_ONLY, False),
        (JPEG_BYTES, False),
        (WEBP_STATIC, False),
    ],
)
def test_png_declares_animation_walks_the_chunks_until_the_image_data(
    content, expected
):
    assert png_declares_animation(content) is expected


# ---------------------------------------------------------------------------
# WEBP animation marks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flags", (0x00, 0x01, 0x04, 0x08))
def test_webp_vp8x_flags_without_the_animation_bit_are_static(flags):
    assert webp_declares_animation(webp(webp_chunk(b"VP8X", webp_vp8x(flags)))) is False


@pytest.mark.parametrize("flags", (0x02, 0x03, 0x0A))
def test_webp_vp8x_animation_bit_is_detected(flags):
    assert webp_declares_animation(webp(webp_chunk(b"VP8X", webp_vp8x(flags)))) is True


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (WEBP_STATIC, False),
        (WEBP_ANIMATED_VP8X, True),
        (WEBP_ANIM, True),
        (WEBP_TRUNCATED, False),
        (WEBP_HEADER_ONLY, False),
        (b"not-a-webp", False),
        (PNG_STATIC, False),
    ],
)
def test_webp_declares_animation_walks_the_chunks(content, expected):
    assert webp_declares_animation(content) is expected
