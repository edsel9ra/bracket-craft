import csv
import io
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import ValidationError

from app.core.config import get_settings
from app.modules.tournaments.schemas import CreateRosterPlayerRequest


class RosterImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedRosterRow:
    line_number: int
    payload: CreateRosterPlayerRequest
    photo_filename: str | None


@dataclass(frozen=True)
class PhotoFile:
    content: bytes
    content_type: str
    extension: str


REQUIRED_COLUMNS = {"first_name", "last_name", "national_id", "birth_date", "dorsal_number"}
IMAGE_TYPES = {
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".webp": ("image/webp", b"RIFF"),
}


def _normalize_photo_filename(value: str) -> str:
    normalized = posixpath.normpath(value.strip().replace("\\", "/"))
    path = PurePosixPath(normalized)
    if not value.strip() or normalized in {".", ""} or path.is_absolute() or ".." in path.parts:
        raise RosterImportError("photo_filename contiene una ruta inválida")
    return normalized


def _parse_bool(value: str, line_number: int) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"", "0", "false", "no", "n", "f"}:
        return False
    if normalized in {"1", "true", "yes", "si", "sí", "s", "y", "t"}:
        return True
    raise RosterImportError(f"Fila {line_number}: photo_consent debe ser true o false")


def parse_roster_csv(raw: bytes, team_id: UUID) -> list[ImportedRosterRow]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RosterImportError("El archivo debe estar codificado en UTF-8") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise RosterImportError("El archivo está vacío") from exc

    columns = [column.strip().casefold() for column in header]
    if len(columns) != len(set(columns)):
        raise RosterImportError("El encabezado contiene columnas duplicadas")
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise RosterImportError(f"Faltan columnas obligatorias: {', '.join(sorted(missing))}")

    settings = get_settings()
    imported: list[ImportedRosterRow] = []
    seen_documents: set[tuple[str, str, str]] = set()
    for line_number, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values):
            continue
        if len(values) > len(columns):
            raise RosterImportError(f"Fila {line_number}: contiene más valores que columnas")
        row = dict(zip(columns, values + [""] * (len(columns) - len(values))))
        document_type = row.get("document_type", "").strip() or "internal"
        issuing_country = row.get("issuing_country", "").strip() or "COL"
        national_id = row.get("national_id", "").strip()
        duplicate_key = (document_type.casefold(), issuing_country.casefold(), national_id)
        if duplicate_key in seen_documents:
            raise RosterImportError(f"Fila {line_number}: documento repetido en el archivo")
        seen_documents.add(duplicate_key)
        try:
            payload = CreateRosterPlayerRequest(
                team_id=team_id,
                first_name=row.get("first_name", "").strip(),
                last_name=row.get("last_name", "").strip(),
                document_type=document_type,
                national_id=national_id,
                issuing_country=issuing_country,
                birth_date=row.get("birth_date", "").strip(),
                dorsal_number=int(row.get("dorsal_number", "").strip()),
                photo_consent=_parse_bool(row.get("photo_consent", ""), line_number),
            )
        except (ValueError, ValidationError) as exc:
            detail = str(exc).splitlines()[0]
            raise RosterImportError(f"Fila {line_number}: {detail}") from exc
        photo_filename = row.get("photo_filename", "").strip() or None
        if photo_filename:
            photo_filename = _normalize_photo_filename(photo_filename)
            if not payload.photo_consent:
                raise RosterImportError(
                    f"Fila {line_number}: photo_consent debe ser true para cargar una foto"
                )
        imported.append(ImportedRosterRow(line_number, payload, photo_filename))
        if len(imported) > settings.storage_max_archive_files:
            raise RosterImportError(f"La carga máxima es de {settings.storage_max_archive_files} jugadores")

    if not imported:
        raise RosterImportError("El archivo no contiene jugadores")
    return imported


def extract_zip_photos(raw: bytes) -> dict[str, PhotoFile]:
    settings = get_settings()
    if len(raw) > settings.storage_max_archive_bytes:
        raise RosterImportError("El archivo ZIP supera el tamaño máximo permitido")
    photos: dict[str, PhotoFile] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise RosterImportError("El paquete de fotos no es un ZIP válido") from exc

    total_bytes = 0
    try:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if len(photos) >= settings.storage_max_archive_files:
                raise RosterImportError("El ZIP contiene demasiadas imágenes")
            filename = _normalize_photo_filename(info.filename)
            extension = PurePosixPath(filename).suffix.casefold()
            image_type = IMAGE_TYPES.get(extension)
            if image_type is None:
                continue
            if info.file_size > settings.storage_max_image_bytes:
                raise RosterImportError(f"La imagen {filename} supera el tamaño máximo permitido")
            total_bytes += info.file_size
            if total_bytes > settings.storage_max_archive_bytes:
                raise RosterImportError("Las imágenes del ZIP superan el tamaño máximo permitido")
            content = archive.read(info)
            photo = validate_photo_content(content, filename)
            key = filename.casefold()
            if key in photos:
                raise RosterImportError(f"El ZIP contiene nombres de imagen duplicados: {filename}")
            photos[key] = photo
    finally:
        archive.close()
    return photos


def validate_photo_content(content: bytes, filename: str) -> PhotoFile:
    settings = get_settings()
    extension = PurePosixPath(filename).suffix.casefold()
    image_type = IMAGE_TYPES.get(extension)
    if image_type is None:
        raise RosterImportError(f"La imagen {filename} debe ser JPG, PNG o WEBP")
    if len(content) > settings.storage_max_image_bytes:
        raise RosterImportError(f"La imagen {filename} supera el tamaño máximo permitido")
    content_type, signature = image_type
    if not content.startswith(signature):
        raise RosterImportError(f"La imagen {filename} no tiene un contenido válido")
    if extension == ".webp" and content[8:12] != b"WEBP":
        raise RosterImportError(f"La imagen {filename} no tiene un contenido WEBP válido")
    return PhotoFile(content, content_type, extension)
