import io
import zipfile
from uuid import uuid4

import pytest

from app.modules.tournaments.roster_import import (
    RosterImportError,
    extract_zip_photos,
    parse_roster_csv,
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
