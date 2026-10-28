"""Pruebas puras de los códigos de dominio de la spec 024 (formatos de juego).

No requieren base de datos: verifican que las excepciones existan con el código
estable y el status 409, siguiendo el patrón de los errores codificados.
"""

from app.modules.matches.errors import (
    FORMATION_NOT_SUPPORTED_FOR_FORMAT,
    PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED,
    FormationNotSupportedForFormat,
    PublishedFormationMustBeUnpublished,
)


def test_formation_not_supported_for_format_code() -> None:
    exc = FormationNotSupportedForFormat()
    assert exc.status_code == 409
    assert exc.code == "FORMATION_NOT_SUPPORTED_FOR_FORMAT"
    assert exc.code == FORMATION_NOT_SUPPORTED_FOR_FORMAT


def test_published_formation_must_be_unpublished_code() -> None:
    exc = PublishedFormationMustBeUnpublished()
    assert exc.status_code == 409
    assert exc.code == "PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED"
    assert exc.code == PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED


def test_detail_is_string() -> None:
    for exc in (FormationNotSupportedForFormat(), PublishedFormationMustBeUnpublished()):
        assert isinstance(exc.detail, str)
        assert str(exc.detail) == exc.detail
