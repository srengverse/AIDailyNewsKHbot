"""Poster rendering for Khmer Dharma posts using Pillow."""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .models import DharmaContent

CANVAS_SIZE = 1200
MARGIN = 92
GOLD = (226, 190, 88, 255)
CREAM = (252, 247, 231, 255)
MUTED_GOLD = (222, 204, 145, 255)


@dataclass(frozen=True, slots=True)
class RenderedPoster:
    """A generated JPEG poster and its local output path."""

    image_bytes: bytes
    output_path: Path
    checksum: str


def _interpolate(first: tuple[int, int, int], second: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * t) for a, b in zip(first, second, strict=True))


def _paint_background() -> Image.Image:
    """Create a dark blue-to-teal meditative gradient with a soft central glow."""
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE))
    pixels = image.load()
    start = (10, 27, 52)
    end = (22, 69, 80)
    center_x = center_y = CANVAS_SIZE / 2
    for y in range(CANVAS_SIZE):
        vertical = y / (CANVAS_SIZE - 1)
        base = _interpolate(start, end, vertical)
        for x in range(CANVAS_SIZE):
            distance = math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2) / (CANVAS_SIZE * 0.72)
            glow = max(0.0, 1.0 - distance) * 0.14
            pixels[x, y] = tuple(min(255, round(channel + 255 * glow)) for channel in base) + (255,)
    return image


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.is_file():
        raise FileNotFoundError(
            f"Khmer font was not found at {path}. Set FONT_PATH to a Unicode Khmer .ttf file."
        )
    return ImageFont.truetype(str(path), size=size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap mainly by Khmer word separators while retaining long character sequences safely."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
            continue
        # Fallback for one long sequence without normal word breaks.
        segment = ""
        for character in word:
            candidate = segment + character
            if draw.textlength(candidate, font=font) <= max_width:
                segment = candidate
            else:
                if segment:
                    lines.append(segment)
                segment = character
        current = segment
    if current:
        lines.append(current)
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    first_y: int,
    color: tuple[int, int, int, int],
    line_spacing: int,
) -> int:
    y = first_y
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        text_width = box[2] - box[0]
        draw.text(((CANVAS_SIZE - text_width) / 2, y), line, font=font, fill=color)
        y += (box[3] - box[1]) + line_spacing
    return y


def _draw_dharma_wheel(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int) -> None:
    """Draw a simple non-text Dharma wheel motif so no symbol font is needed."""
    x, y = center
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=GOLD, width=4)
    draw.ellipse([x - radius // 3, y - radius // 3, x + radius // 3, y + radius // 3], outline=GOLD, width=3)
    for angle in range(0, 360, 45):
        radians = math.radians(angle)
        x2 = x + int(math.cos(radians) * radius)
        y2 = y + int(math.sin(radians) * radius)
        draw.line([x, y, x2, y2], fill=GOLD, width=3)


class DharmaPosterRenderer:
    """Render a calm, standardized, square poster ready for Facebook publishing."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def render(self, content: DharmaContent) -> RenderedPoster:
        image = _paint_background()
        draw = ImageDraw.Draw(image)

        # Exterior and interior double-gold border.
        draw.rounded_rectangle([38, 38, 1162, 1162], radius=28, outline=GOLD, width=5)
        draw.rounded_rectangle([54, 54, 1146, 1146], radius=20, outline=(168, 139, 63, 255), width=1)
        _draw_dharma_wheel(draw, (600, 150), 43)

        title_font = _load_font(self._settings.font_path, 43)
        label_font = _load_font(self._settings.font_path, 28)
        source_font = _load_font(self._settings.font_path, 29)

        title_lines = _wrap_text(draw, content.title, title_font, CANVAS_SIZE - 2 * MARGIN)
        if len(title_lines) > 2:
            title_lines = title_lines[:2]
        _draw_centered_lines(draw, title_lines, title_font, 225, GOLD, 10)
        draw.line([(MARGIN + 85, 350), (CANVAS_SIZE - MARGIN - 85, 350)], fill=(174, 144, 66, 190), width=2)

        # Ensure the quote occupies the intended panel without crossing the source section.
        quote_font_size = 52
        quote_lines: list[str] = []
        max_quote_height = 425
        while quote_font_size >= 30:
            candidate_font = _load_font(self._settings.font_path, quote_font_size)
            candidate_lines = _wrap_text(draw, f"“{content.buddhavacana}”", candidate_font, CANVAS_SIZE - 2 * MARGIN)
            line_height = quote_font_size + 17
            if len(candidate_lines) * line_height <= max_quote_height:
                quote_lines = candidate_lines
                quote_font = candidate_font
                break
            quote_font_size -= 2
        else:
            raise ValueError("The Dharma quote cannot fit safely in the poster layout.")

        quote_y = 425 + max(0, (max_quote_height - len(quote_lines) * (quote_font_size + 17)) // 2)
        _draw_centered_lines(draw, quote_lines, quote_font, quote_y, CREAM, 17)

        draw.line([(MARGIN + 85, 885), (CANVAS_SIZE - MARGIN - 85, 885)], fill=(174, 144, 66, 190), width=2)
        source_label = "ប្រភពព្រះធម៌"
        source_lines = _wrap_text(draw, f"{source_label}៖ {content.pali_source}", source_font, CANVAS_SIZE - 2 * MARGIN - 60)
        if len(source_lines) > 2:
            source_lines = source_lines[:2]
        _draw_centered_lines(draw, source_lines, source_font, 930, MUTED_GOLD, 9)
        footer = "DharmaPostAI · សូមអនុមោទនា"
        footer_box = draw.textbbox((0, 0), footer, font=label_font)
        draw.text(
            ((CANVAS_SIZE - (footer_box[2] - footer_box[0])) / 2, 1080),
            footer,
            font=label_font,
            fill=(190, 201, 199, 255),
        )

        self._settings.poster_output_dir.mkdir(parents=True, exist_ok=True)
        encoded = io.BytesIO()
        image.convert("RGB").save(encoded, format="JPEG", quality=93, optimize=True)
        image_bytes = encoded.getvalue()
        checksum = hashlib.sha256(image_bytes).hexdigest()
        output_path = self._settings.poster_output_dir / f"dharma-{checksum[:16]}.jpg"
        output_path.write_bytes(image_bytes)
        return RenderedPoster(image_bytes=image_bytes, output_path=output_path, checksum=checksum)
