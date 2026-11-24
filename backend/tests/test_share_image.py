"""Composición de imágenes de vista previa (spec 043, T1)."""

import io

import pytest
from PIL import Image

from app.modules.tournaments import share_image
from app.modules.tournaments.share_image import (
    BRAND_FALLBACK_PATH,
    HEIGHT,
    LABELS,
    WIDTH,
    brand_card,
    contrast_ratio,
    fit_text,
    load_font,
    result_card,
    tournament_card,
)


def open_png(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def assert_card(data: bytes) -> Image.Image:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    image = open_png(data)
    assert image.format == "PNG"
    assert image.size == (WIDTH, HEIGHT) == (1200, 630)
    return image


@pytest.mark.parametrize("lang", ["es", "en"])
def test_tournament_card_is_a_1200x630_png(lang):
    assert_card(tournament_card(name="Copa Andina", season="2026", status="live", lang=lang))


@pytest.mark.parametrize("lang", ["es", "en"])
def test_result_card_is_a_1200x630_png(lang):
    assert_card(result_card(
        tournament_name="Copa Andina", home_team="Atlético Sur", away_team="Deportivo Norte",
        home_score=2, away_score=2, home_penalties=4, away_penalties=3, lang=lang,
    ))


@pytest.mark.parametrize("lang", ["es", "en"])
def test_brand_card_is_a_1200x630_png(lang):
    assert_card(brand_card(lang))


def test_cards_differ_by_content_and_language():
    es = tournament_card(name="Copa", season="2026", status="finished", lang="es")
    en = tournament_card(name="Copa", season="2026", status="finished", lang="en")
    other = tournament_card(name="Liga", season="2026", status="finished", lang="es")
    assert len({es, en, other}) == 3


def test_rendering_is_deterministic():
    kwargs = dict(name="Copa", season="2026", status="published", lang="es")
    assert tournament_card(**kwargs) == tournament_card(**kwargs)


def test_penalties_are_drawn_only_when_present():
    base = dict(tournament_name="Copa", home_team="A", away_team="B",
                home_score=1, away_score=1, lang="es")
    without = result_card(**base, home_penalties=None, away_penalties=None)
    with_pen = result_card(**base, home_penalties=5, away_penalties=4)
    assert without != with_pen


def test_labels_cover_both_languages_and_public_statuses():
    assert set(LABELS) == {"es", "en"}
    for labels in LABELS.values():
        for key in ("status.published", "status.live", "status.finished", "status.other",
                    "tournament", "final_result", "penalties", "tagline"):
            assert labels[key].strip()
    assert LABELS["es"]["final_result"] == "Resultado final"
    assert LABELS["en"]["final_result"] == "Final result"


def test_unknown_status_uses_generic_label():
    assert_card(tournament_card(name="Copa", season="2026", status="weird", lang="es"))


def test_fit_text_keeps_short_text():
    font = load_font(48, 700)
    assert fit_text("Copa", font, 1000) == "Copa"


@pytest.mark.parametrize("text", [
    "Campeonato Intercolegial Metropolitano de Fútbol Juvenil Sub-17 Temporada Apertura",
    "Ñandú Peñarol Águilas Doradas Ünïcödé " * 6,
    "東京サッカー選手権大会" * 10,
])
def test_fit_text_truncates_with_ellipsis_within_width(text):
    font = load_font(64, 800)
    fitted = fit_text(text, font, 900)
    assert fitted.endswith("…")
    assert font.getlength(fitted) <= 900
    assert text.startswith(fitted[:-1].rstrip())


def test_long_and_non_latin_names_never_break_rendering():
    long = "Club Social y Deportivo de los Trabajadores Unidos del Valle " * 4
    assert_card(tournament_card(name=long, season=long, status="live", lang="es"))
    assert_card(result_card(
        tournament_name="東京" * 40, home_team=long, away_team="Ñandú 東京 FC" * 10,
        home_score=10, away_score=0, home_penalties=None, away_penalties=None, lang="en",
    ))


def test_text_colors_meet_contrast():
    for color in (share_image.INK, share_image.MUTED, share_image.ACCENT):
        assert contrast_ratio(color, share_image.CANVAS) >= 4.5
    assert contrast_ratio(share_image.ACCENT_INK, share_image.ACCENT) >= 4.5


def test_brand_fallback_asset_is_the_rendered_brand_card():
    stored = assert_card(BRAND_FALLBACK_PATH.read_bytes())
    rendered = open_png(brand_card("es"))
    assert stored.convert("RGB").tobytes() == rendered.convert("RGB").tobytes()
