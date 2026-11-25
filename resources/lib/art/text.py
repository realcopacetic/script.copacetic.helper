# author: realcopacetic

from pathlib import Path

import xbmcvfs
from PIL import Image, ImageDraw, ImageFont

from resources.lib.art.policy import ColorConfig
from resources.lib.art.io import write_image
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.text import fit_paragraphs, plain_text
from resources.lib.shared.utilities import TEXTS, create_dir, validate_path

# Bump when the render logic changes so stale cached PNGs are superseded.
_RENDER_VERSION = "6"


class TextRenderer:
    """
    Rasterise wrapped text to a cached white-on-transparent PNG mask.
    Colour is applied skin-side via colordiffuse; this output is colourless.
    """

    def __init__(self) -> None:
        """Ensure the text-mask cache folder exists and load PNG settings."""
        create_dir(TEXTS)
        self.cfg = ColorConfig()

    def render(
        self,
        *,
        text: str,
        font_path: str,
        font_size: int,
        box_width: int,
        max_height: int,
        line_height: float = 1.3,
        letter_spacing: float = 0.0,
        scale: int = 1,
        supersample: int = 2,
    ) -> tuple[str, int] | None:
        """
        Rasterise text and return a cached PNG path (cache-first, content-keyed),
        the image at scale times the box, so a 4K GUI draws it 1:1.

        :param text: Already-localised string; Kodi's tags drop, a [CR] breaks the line.
        :param font_path: special:// or absolute path to a .ttf/.otf font.
        :param font_size: Font size in skin pixels.
        :param box_width: Wrap width in skin pixels.
        :param max_height: Hard ceiling in skin pixels; wrap is clamped to whole lines.
        :param line_height: Line pitch as a multiple of font size.
        :param letter_spacing: Tracking as a percentage of font size.
        :param scale: Image pixels per skin pixel (gui_scale).
        :param supersample: Least draw scale over the box (2 = 2x, then down to scale).
        :return: (PNG path, height in skin pixels) tuple, or None if nothing rendered.
        """
        if not (text := plain_text(text)):
            return None

        path = self._cache_path(
            text,
            font_path,
            font_size,
            box_width,
            max_height,
            line_height,
            letter_spacing,
            scale,
            supersample,
        )

        try:
            if validate_path(path):
                with Image.open(path) as im:
                    return path, -(-im.height // scale)

            s = max(scale, supersample)
            font = ImageFont.truetype(xbmcvfs.translatePath(font_path), font_size * s)
            ascent, descent = font.getmetrics()
            natural = ascent + descent
            advance = round(font_size * line_height * s)
            tracking = font_size * s * (letter_spacing / 100.0)
            max_lines = max(1, (max_height * s - natural) // advance + 1)

            lines = fit_paragraphs(font, text, box_width * s, max_lines, tracking)
            if not lines:
                return None

            w = box_width * s
            h = advance * (len(lines) - 1) + natural
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            for li, line in enumerate(lines):
                y = li * advance
                for ci, ch in enumerate(line):
                    x = round(font.getlength(line[:ci]) + ci * tracking)
                    draw.text((x, y), ch, font=font, fill=255)

            out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
            out.putalpha(mask)
            if s > scale:
                out = out.resize((box_width * scale, h * scale // s), Image.LANCZOS)

            write_image(path, out, "PNG", self.cfg)
            return path, -(-out.height // scale)
        except Exception:
            log.exception(f"{self.__class__.__name__} → Unable to render text")
            return None

    def _cache_path(self, *parts: object) -> str:
        """Build the content-hash cache path from output-affecting inputs."""
        key = HashManager.short_hash_str(
            "|".join((_RENDER_VERSION, *map(str, parts))), length=16
        )
        return str(Path(TEXTS) / f"{key}.png")
