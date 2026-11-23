"""Imágenes de vista previa 1200×630 (spec 043, RF-003/RF-004).

Solo texto y colores de marca: nunca escudos, fotos ni datos fuera de la
consulta pública. Funciones puras y deterministas: mismos datos, mismos bytes.
"""

import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Lang = Literal["es", "en"]

WIDTH, HEIGHT = 1200, 630
MARGIN = 72
CONTENT_WIDTH = WIDTH - 2 * MARGIN

# Paleta oscura de marca (frontend/app/utils/designTokens.ts).
CANVAS = "#0c0f0c"
SURFACE = "#151814"
LINE = "#3b4538"
INK = "#f4f0e7"
MUTED = "#a6aa9f"
ACCENT = "#d4f36a"
ACCENT_INK = "#17200f"

_ASSETS = Path(__file__).resolve().parents[2] / "assets"
FONT_PATH = _ASSETS / "fonts" / "Archivo[wdth,wght].ttf"
BRAND_FALLBACK_PATH = _ASSETS / "share" / "brand-fallback.png"

ELLIPSIS = "…"

LABELS: dict[str, dict[str, str]] = {
    "es": {
        "status.published": "Publicado",
        "status.live": "En vivo",
        "status.finished": "Finalizado",
        "status.other": "Torneo",
        "tournament": "Torneo",
        "final_result": "Resultado final",
        "penalties": "Penaltis",
        "tagline": "El sistema operativo para torneos con reglas configurables.",
    },
    "en": {
        "status.published": "Published",
        "status.live": "Live",
        "status.finished": "Finished",
        "status.other": "Tournament",
        "tournament": "Tournament",
        "final_result": "Final result",
        "penalties": "Penalties",
        "tagline": "The operating system for tournaments with configurable rules.",
    },
}


@lru_cache(maxsize=32)
def load_font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), size)
    font.set_variation_by_axes([weight, 100])  # ejes: Weight, Width
    return font


def fit_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str:
    text = " ".join(text.split())
    if font.getlength(text) <= max_width:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if font.getlength(text[:mid].rstrip() + ELLIPSIS) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ELLIPSIS


def _fitted(text: str, sizes: tuple[int, ...], weight: int, max_width: float) -> tuple[str, ImageFont.FreeTypeFont]:
    """Prueba tamaños de mayor a menor; con el menor recorta con «…»."""
    for size in sizes:
        font = load_font(size, weight)
        if font.getlength(" ".join(text.split())) <= max_width:
            return " ".join(text.split()), font
    font = load_font(sizes[-1], weight)
    return fit_text(text, font, max_width), font


def _relative_luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), CANVAS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 16, HEIGHT), fill=ACCENT)
    draw.text((MARGIN, 56), "BRACKET CRAFT", font=load_font(28, 800), fill=ACCENT)
    draw.line((MARGIN, HEIGHT - 72, WIDTH - MARGIN, HEIGHT - 72), fill=LINE, width=2)
    return image, draw


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _labels(lang: Lang) -> dict[str, str]:
    return LABELS[lang if lang in LABELS else "es"]


def tournament_card(*, name: str, season: str, status: str, lang: Lang) -> bytes:
    labels = _labels(lang)
    image, draw = _canvas()
    eyebrow = fit_text(f"{labels['tournament']} · {season}", load_font(32, 500), CONTENT_WIDTH)
    draw.text((MARGIN, 196), eyebrow, font=load_font(32, 500), fill=MUTED)
    title, title_font = _fitted(name, (104, 88, 76, 64), 800, CONTENT_WIDTH)
    draw.text((MARGIN, 250), title, font=title_font, fill=INK)

    status_label = labels.get(f"status.{status}", labels["status.other"])
    pill_font = load_font(30, 700)
    pill_width = int(pill_font.getlength(status_label)) + 48
    top = 420
    draw.rounded_rectangle((MARGIN, top, MARGIN + pill_width, top + 56), radius=28, fill=ACCENT)
    draw.text((MARGIN + 24, top + 28), status_label, font=pill_font, fill=ACCENT_INK, anchor="lm")
    return _png(image)


def result_card(
    *,
    tournament_name: str,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    home_penalties: int | None,
    away_penalties: int | None,
    lang: Lang,
) -> bytes:
    labels = _labels(lang)
    image, draw = _canvas()
    draw.text((MARGIN, 140), labels["final_result"], font=load_font(30, 700), fill=ACCENT)
    subtitle = fit_text(tournament_name, load_font(30, 500), CONTENT_WIDTH)
    draw.text((MARGIN, 182), subtitle, font=load_font(30, 500), fill=MUTED)

    score_font = load_font(96, 900)
    score_column = 180
    name_width = CONTENT_WIDTH - score_column - 24
    for row, (team, score) in enumerate(((home_team, home_score), (away_team, away_score))):
        top = 252 + row * 132
        draw.rounded_rectangle((MARGIN - 8, top, WIDTH - MARGIN + 8, top + 116), radius=20, fill=SURFACE)
        name, name_font = _fitted(team, (60, 52, 44), 800, name_width)
        draw.text((MARGIN + 16, top + 58), name, font=name_font, fill=INK, anchor="lm")
        draw.text((WIDTH - MARGIN - 16, top + 58), str(score), font=score_font, fill=INK, anchor="rm")

    if home_penalties is not None and away_penalties is not None:
        penalties = f"{labels['penalties']} {home_penalties}–{away_penalties}"
        draw.text((MARGIN, HEIGHT - 48), penalties, font=load_font(28, 700), fill=ACCENT, anchor="lm")
    return _png(image)


def brand_card(lang: Lang) -> bytes:
    labels = _labels(lang)
    image, draw = _canvas()
    draw.text((MARGIN, 220), "Bracket Craft", font=load_font(120, 900), fill=INK)
    tagline = fit_text(labels["tagline"], load_font(36, 500), CONTENT_WIDTH)
    draw.text((MARGIN, 390), tagline, font=load_font(36, 500), fill=MUTED)
    return _png(image)
