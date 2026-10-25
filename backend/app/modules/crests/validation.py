"""Pure validation helpers for team crests (RF-28…RF-37, RNF-1…RNF-3).

No function reads the clock, the configuration, the network or the database:
the size limit, the identifiers and the random token enter as parameters. The
content is never decoded, re-encoded or converted; only the signatures and the
container marks are inspected, so the declared limits are exactly these:

* the type comes from the content signature, never from a file name or from the
  extension chosen by the person (a PNG name with JPEG bytes is a JPEG);
* the size limit is the one received (the caller takes it from
  ``settings.storage_max_image_bytes``);
* PNG animation is detected only through an ``acTL`` chunk placed before the
  first ``IDAT``; WEBP animation through the ``VP8X`` animation bit or an
  ``ANIM`` chunk;
* a truncated or unreadable container that keeps an admitted header is accepted
  and served: corruption or animation that only shows when decoding is not
  detected and this limitation is documented.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.modules.crests.errors import (
    CREST_ANIMATION_UNSUPPORTED,
    CREST_FILE_EMPTY,
    CREST_FORMAT_UNSUPPORTED,
    CREST_TOO_LARGE,
    CrestError,
)

_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RIFF_SIGNATURE = b"RIFF"
_WEBP_SIGNATURE = b"WEBP"

#: Content type of every admitted extension. The detector returns the extension
#: and this table fixes what the storage declares as ``ContentType``.
IMAGE_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

#: Extensions the detector can return. The object key only accepts these, so a
#: person-chosen extension never reaches the storage.
ALLOWED_CREST_EXTENSIONS: tuple[str, ...] = (".jpg", ".png", ".webp")

#: Bytes of a PNG chunk prefix: 4 length + 4 type.
_PNG_CHUNK_HEADER = 8
#: Bytes of a PNG chunk including its CRC.
_PNG_CHUNK_OVERHEAD = 12
#: Bytes of a RIFF chunk header: 4 fourcc + 4 little-endian size.
_WEBP_CHUNK_HEADER = 8
#: VP8X flag that declares an extended-format WebP as animated.
_WEBP_ANIMATION_FLAG = 0x02


@dataclass(frozen=True)
class CrestFile:
    """Admitted crest content with the type derived from its own bytes."""

    content: bytes
    content_type: str
    extension: str


def detect_image_type(content: bytes) -> str | None:
    """Return ``.jpg``/``.png``/``.webp`` from the signature, or ``None``.

    The name and the declared ``Content-Type`` are irrelevant: only the first
    bytes decide. GIF (``GIF87a``/``GIF89a``), SVG, XML and HTML return ``None``.
    """

    if content.startswith(_JPEG_SIGNATURE):
        return ".jpg"
    if content.startswith(_PNG_SIGNATURE):
        return ".png"
    if (
        len(content) >= 12
        and content[:4] == _RIFF_SIGNATURE
        and content[8:12] == _WEBP_SIGNATURE
    ):
        return ".webp"
    return None


def png_declares_animation(content: bytes) -> bool:
    """Return whether a PNG declares animation before its image data.

    Only the chunk headers are read. ``acTL`` before the first ``IDAT`` (or
    ``IEND``) is an animation mark; a truncated or unreadable chunk list returns
    ``False`` because the animation cannot be proven and the file is accepted.
    """

    if not content.startswith(_PNG_SIGNATURE):
        return False

    position = len(_PNG_SIGNATURE)
    total = len(content)
    while position + _PNG_CHUNK_HEADER <= total:
        length = int.from_bytes(content[position : position + 4], "big")
        chunk_type = content[position + 4 : position + 8]
        if chunk_type == b"acTL":
            # The mark declares animation even if the chunk itself is truncated:
            # it is authoritative and the file is rejected.
            return True
        if chunk_type in (b"IDAT", b"IEND"):
            return False
        if position + _PNG_CHUNK_OVERHEAD + length > total:
            return False
        position += _PNG_CHUNK_OVERHEAD + length
    return False


def webp_declares_animation(content: bytes) -> bool:
    """Return whether a WebP declares animation in ``VP8X`` or with ``ANIM``.

    Only the RIFF chunk headers are read. A truncated or unreadable chunk list
    returns ``False`` because the animation cannot be proven and the file is
    accepted.
    """

    if (
        len(content) < 12
        or content[:4] != _RIFF_SIGNATURE
        or content[8:12] != _WEBP_SIGNATURE
    ):
        return False

    position = 12
    total = len(content)
    while position + _WEBP_CHUNK_HEADER <= total:
        fourcc = content[position : position + 4]
        size = int.from_bytes(content[position + 4 : position + 8], "little")
        if fourcc == b"ANIM":
            return True
        if fourcc == b"VP8X":
            if position + 9 > total:
                return False
            if content[position + 8] & _WEBP_ANIMATION_FLAG:
                return True
        if position + _WEBP_CHUNK_HEADER + size > total:
            return False
        position += _WEBP_CHUNK_HEADER + size + (size & 1)
    return False


def validate_crest_content(content: bytes, *, max_bytes: int) -> CrestFile:
    """Admit or reject crest content, without decoding it.

    Order: empty → ``CREST_FILE_EMPTY``; over the received limit →
    ``CREST_TOO_LARGE``; unsupported content → ``CREST_FORMAT_UNSUPPORTED``;
    detectable animation → ``CREST_ANIMATION_UNSUPPORTED``. An unreadable
    container is accepted (declared risk). The returned extension is the one
    derived from the content.
    """

    if not content:
        raise CrestError(CREST_FILE_EMPTY)
    if len(content) > max_bytes:
        raise CrestError(CREST_TOO_LARGE)

    extension = detect_image_type(content)
    if extension is None:
        raise CrestError(CREST_FORMAT_UNSUPPORTED)

    if extension == ".png" and png_declares_animation(content):
        raise CrestError(CREST_ANIMATION_UNSUPPORTED)
    if extension == ".webp" and webp_declares_animation(content):
        raise CrestError(CREST_ANIMATION_UNSUPPORTED)

    return CrestFile(
        content=content,
        content_type=IMAGE_CONTENT_TYPES[extension],
        extension=extension,
    )


def crest_object_key(
    organization_id: UUID | str,
    tournament_id: UUID | str,
    team_id: UUID | str,
    extension: str,
    *,
    token: str | None = None,
) -> str:
    """Return the private object key of a team crest.

    Layout: ``private/organizations/{org}/tournaments/{tournament}/teams/{team}/
    {token}{extension}``. ``extension`` must be the one derived from the detected
    content, and ``token`` is a random UUID generated here unless a test injects
    one, so the key never depends on the clock, on the team or on the file name.
    The result always satisfies ``core.storage._is_valid_key``.
    """

    if extension not in ALLOWED_CREST_EXTENSIONS:
        raise ValueError(f"Extensión de escudo no admitida: {extension!r}")

    if token is None:
        token = str(uuid4())
    elif not isinstance(token, str) or not token or "/" in token or ".." in token:
        raise ValueError("El token del escudo no es válido")

    return (
        f"private/organizations/{organization_id}"
        f"/tournaments/{tournament_id}"
        f"/teams/{team_id}/{token}{extension}"
    )
