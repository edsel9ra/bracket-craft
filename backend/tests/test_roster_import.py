import io
import zipfile
from uuid import uuid4

import pytest

from app.modules.tournaments import roster_import
from app.modules.tournaments.roster_import import (
    RosterImportError,
    extract_zip_photos,
    parse_roster_csv,
    validate_photo_content,
)


def test_parse_roster_csv_supports_bom_quotes_and_photo_reference():
    raw = (
        "\ufefffirst_name,last_name,national_id,birth_date,dorsal_number,photo_consent,photo_filename\n"
        'Ana,"De la Cruz",ID-1,2000-01-02,7,true,photos/ana.JPG\n'
    ).encode("utf-8")

    rows = parse_roster_csv(raw, uuid4())

    assert len(rows) == 1
    assert rows[0].payload.first_name == "Ana"
    assert rows[0].payload.last_name == "De la Cruz"
    assert rows[0].payload.photo_consent is True
    assert rows[0].photo_filename == "photos/ana.JPG"


def test_parse_roster_csv_requires_the_birth_date_column():
    raw = (
        "first_name,last_name,national_id,dorsal_number\n"
        "Ana,Player,ID-1,7\n"
    ).encode()

    with pytest.raises(RosterImportError, match="birth_date"):
        parse_roster_csv(raw, uuid4())


def test_parse_roster_csv_rejects_the_whole_file_on_an_invalid_birth_date():
    raw = (
        "first_name,last_name,national_id,birth_date,dorsal_number\n"
        "Ana,Player,ID-1,2000-01-02,7\n"
        "Bruno,Player,ID-2,2999-01-01,8\n"
    ).encode()

    with pytest.raises(RosterImportError) as error:
        parse_roster_csv(raw, uuid4())

    message = str(error.value)
    assert "Fila 3" in message
    # The rejected value is never repeated in the error message (RF-007/RF-012).
    assert "2999-01-01" not in message


def test_parse_roster_csv_rejects_photo_path_traversal():
    raw = (
        "first_name,last_name,national_id,birth_date,dorsal_number,photo_filename\n"
        "Ana,Player,ID-1,2000-01-02,7,../ana.jpg\n"
    ).encode()

    with pytest.raises(RosterImportError, match="ruta inválida"):
        parse_roster_csv(raw, uuid4())


def test_extract_zip_photos_validates_images_and_normalizes_lookup():
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("photos/Ana.JPG", b"\xff\xd8\xffplayer")

    photos = extract_zip_photos(archive_bytes.getvalue())

    assert "photos/ana.jpg" in photos
    assert photos["photos/ana.jpg"].content_type == "image/jpeg"


def test_extract_zip_photos_rejects_invalid_image_content():
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("player.png", b"not-an-image")

    with pytest.raises(RosterImportError, match="contenido válido"):
        extract_zip_photos(archive_bytes.getvalue())


PNG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(kind, data=b""):
    return len(data).to_bytes(4, "big") + kind + data + b"\x00" * 4


def _webp(chunk, data=b""):
    body = b"WEBP" + chunk + len(data).to_bytes(4, "little") + data
    return b"RIFF" + len(body).to_bytes(4, "little") + body


@pytest.mark.parametrize("name,content", [
    ("player.png", PNG + _png_chunk(b"acTL", b"\x00" * 8)),
    ("player.png", PNG + b"\x00\x00\x00\x99acTL"),
    ("player.webp", _webp(b"VP8X", b"\x02" + b"\x00" * 9)),
    ("player.webp", _webp(b"ANIM", b"\x00" * 6)),
])
@pytest.mark.parametrize("in_archive", [False, True])
def test_photo_rejects_declared_animation(name, content, in_archive):
    with pytest.raises(RosterImportError, match="no puede ser animada"):
        if in_archive:
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w") as archive:
                archive.writestr(name, content)
            extract_zip_photos(archive_bytes.getvalue())
        else:
            validate_photo_content(content, name)


@pytest.mark.parametrize("name,content,content_type", [
    ("player.jpg", b"\xff\xd8\xffstatic", "image/jpeg"),
    ("player.JPEG", b"\xff\xd8\xffstatic", "image/jpeg"),
    ("player.png", PNG + _png_chunk(b"IDAT"), "image/png"),
    ("player.png", PNG + b"\x00\x00", "image/png"),
    ("player.webp", _webp(b"VP8X", b"\x00" * 10), "image/webp"),
    ("player.webp", b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
])
def test_photo_preserves_static_formats_and_truncated_container_policy(name, content, content_type):
    photo = validate_photo_content(content, name)
    assert photo.content == content
    assert photo.content_type == content_type
    assert photo.extension == "." + name.rsplit(".", 1)[1].casefold()


@pytest.mark.parametrize("name,content", [
    ("player.png", b""), ("player.jpg", PNG),
    ("player.webp", b"RIFF\x00\x00\x00\x00WAVE"),
    ("player.gif", b"GIF89a"), ("player.svg", b"<svg/>"),
])
def test_photo_rejects_empty_unsupported_or_mismatched_content(name, content):
    with pytest.raises(RosterImportError):
        validate_photo_content(content, name)


def test_photo_preserves_its_size_limit(monkeypatch):
    settings = roster_import.get_settings().model_copy(update={"storage_max_image_bytes": 4})
    monkeypatch.setattr(roster_import, "get_settings", lambda: settings)
    assert validate_photo_content(b"\xff\xd8\xffx", "player.jpg").content_type == "image/jpeg"
    with pytest.raises(RosterImportError, match="tamaño máximo"):
        validate_photo_content(b"\xff\xd8\xffxx", "player.jpg")
