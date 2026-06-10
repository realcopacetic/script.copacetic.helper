# author: realcopacetic

from pathlib import Path

import xbmcvfs
from PIL import Image, ImageDraw, ImageFont

from resources.lib.art.policy import ColorConfig
from resources.lib.art.io import write_image
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.text import sentence_cap
from resources.lib.shared.utilities import TEXTS, create_dir, validate_path

# Bump when the render logic changes so stale cached PNGs are superseded.
_RENDER_VERSION = "3"


class TextRenderer:
    """
    Rasterise wrapped text to a cached white-on-transparent PNG mask.
    Colour is applied skin-side via colordiffuse; this output is colourless.
    """

    _ELLIPSIS = "..."

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

        supersample: int = 2,
    ) -> tuple[str, int] | None:
        """
        Rasterise text and return a cached PNG path (cache-first, content-keyed).

        :param text: Already-localised string to render.
        :param font_path: special:// or absolute path to a .ttf/.otf font.
        :param font_size: Target font size in final (non-supersampled) pixels.
        :param box_width: Wrap/output width in final pixels.
        :param max_height: Hard ceiling; wrap is clamped to whole lines.
         :param line_height: Line pitch as a multiple of font size.
         :param letter_spacing: Tracking as a percentage of font size.
        :param supersample: Draw scale for antialiasing (2 = 2x then downscale).
        :return: (PNG path, pixel height) tuple, or None if nothing rendered.
        """
        if not text:
            return None

        path = self._cache_path(
            text, font_path, font_size, box_width, max_height,
            line_height, letter_spacing, supersample,
        )

        try:
            if validate_path(path):
                with Image.open(path) as im:
                    return path, im.height
                
            s = max(1, supersample)
            font = ImageFont.truetype(xbmcvfs.translatePath(font_path), font_size * s)
            ascent, descent = font.getmetrics()
            natural = ascent + descent
            advance = round(font_size * line_height * s)
            tracking = font_size * s * (letter_spacing / 100.0)
            max_lines = max(1, (max_height * s) // advance)

            lines = self._fit_lines(font, text, box_width * s, max_lines, tracking)
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
            if s > 1:
                out = out.resize((box_width, h // s), Image.LANCZOS)

            write_image(path, out, "PNG", self.cfg)
            return path, out.height
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to render text → {exc}")
            return None

    def _cache_path(self, *parts: object) -> str:
        """Build the content-hash cache path from output-affecting inputs."""
        key = HashManager.short_hash_str(
            "|".join((_RENDER_VERSION, *map(str, parts))), length=16
        )
        return str(Path(TEXTS) / f"{key}.png")

    def _fit_lines(
        self,
        font: ImageFont.FreeTypeFont,
        text: str,
        max_width: int,
        max_lines: int,
        tracking: float = 0.0,
    ) -> list[str]:
        """Wrap to lines; on overflow cap at the last sentence, else ellipsise."""
        lines = self._wrap(font, text, max_width, tracking)
        if len(lines) <= max_lines:
            return lines

        visible = " ".join(lines[:max_lines])
        if capped := sentence_cap(visible):
            return self._wrap(font, capped, max_width, tracking)[:max_lines]

        lines = lines[:max_lines]
        last = lines[-1]
        while " " in last and (
            self._text_width(font, f"{last}{self._ELLIPSIS}", tracking) > max_width
        ):
            last = last.rsplit(" ", 1)[0]
        lines[-1] = f"{last}{self._ELLIPSIS}"
        return lines

    @staticmethod
    def _text_width(font: ImageFont.FreeTypeFont, text: str, tracking: float) -> float:
        """Rendered width of text including uniform letter tracking."""
        return font.getlength(text) + tracking * max(0, len(text) - 1)

    @staticmethod
    def _wrap(
        font: ImageFont.FreeTypeFont, text: str, max_width: int, tracking: float = 0.0
    ) -> list[str]:
        """Greedy word-wrap by advance width; never drops an over-long word."""
        lines: list[str] = []
        cur = ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if not cur or TextRenderer._text_width(font, trial, tracking) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines