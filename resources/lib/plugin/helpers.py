# author: realcopacetic

from __future__ import annotations

import io
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, Collection, Iterable, Mapping

import xbmcvfs
from xbmc import Monitor
from xbmcgui import Window, getCurrentWindowDialogId, getCurrentWindowId

from resources.lib.plugin.geometry import (
    PlacementOpts,
    align_x,
    align_y,
    axis_travel,
    compute_rect,
)
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import TruncateCacheHandler
from resources.lib.shared.text import fit_lines
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    return_label,
    split,
    split_random,
    to_int,
    url_encode,
)

if TYPE_CHECKING:
    from PIL import ImageFont

# Bump when fit_lines/wrap_text change so stale clamp results are superseded.
_CLAMP_VERSION = "1"


def reposition_control(
    control_id: int,
    *,
    x: int | None = None,
    y: int | None = None,
    w: int | None = None,
    h: int | None = None,
) -> None:
    """
    Set any provided geometry on a control; unset axes are left untouched.
    Setters only (no getWidth/getX), so it never reads a control that may be
    mid-layout. Position needs both x and y; a lone axis is ignored.

    :param control_id: Target control id on the current window.
    :param x: New left in px, or None to leave unchanged.
    :param y: New top in px, or None to leave unchanged.
    :param w: New width in px, or None to leave unchanged.
    :param h: New height in px, or None to leave unchanged.
    """
    dialog_id = getCurrentWindowDialogId()
    window_id = dialog_id if dialog_id != 9999 else getCurrentWindowId()
    window = Window(window_id)
    try:
        ctrl = window.getControl(control_id)
    except RuntimeError:
        log.debug(
            f"reposition_control: control {control_id} not found "
            f"in window {window_id}"
        )
        return

    log.debug(
        f"reposition_control: window={window_id} control={control_id} "
        f"type={type(ctrl).__name__} → x={x} y={y} w={w} h={h}"
    )

    if w is not None:
        ctrl.setWidth(w)
    if h is not None:
        ctrl.setHeight(h)
    if x is not None and y is not None:
        ctrl.setPosition(x, y)


def has_value(value: Any) -> bool:
    """Whether a value should be preserved and not overwritten."""
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, dict)):
        return bool(value)
    return True  # ints, bools, floats: treat all as meaningful


def merge_metadata(
    base: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    prefer_incoming: bool = False,
    ignore_keys: Collection[str] = ("art", "file"),
) -> dict[str, Any]:
    """Merge incoming metadata into a base metadata dict.
    Mutates ``base`` in place using has_value rules and overwrite policy.

    :param base: Local metadata dict to update in place.
    :param incoming: Metadata dict to merge values from.
    :param prefer_incoming: If true, prefer incoming over non-empty base.
    :param ignore_keys: Top-level keys to skip entirely when merging.
    :return: Updated base metadata dict.
    """
    incoming_props = incoming.get("properties")
    if isinstance(incoming_props, Mapping):
        local_props = base.setdefault("properties", {})
        for key, incoming_val in incoming_props.items():
            local_val = local_props.get(key)
            if prefer_incoming:
                if has_value(incoming_val):
                    local_props[key] = incoming_val
            else:
                if not has_value(local_val) and has_value(incoming_val):
                    local_props[key] = incoming_val

    for key, incoming_val in incoming.items():
        if key == "properties" or key in ignore_keys:
            continue

        local_val = base.get(key)
        if prefer_incoming:
            if has_value(incoming_val):
                base[key] = incoming_val
        else:
            if not has_value(local_val) and has_value(incoming_val):
                base[key] = incoming_val

    return base


def get_infolabels(target: str, keys: Iterable[str]) -> dict[str, str]:
    """
    Fetch multiple infolabels for the targeted listitem.

    :param target: Container/listitem prefix indicating where to read from.
    :param keys: Iterable of infolabel suffixes.
    :return: Dict mapping suffix → value.
    """
    return {key: infolabel(f"{target}.{key}") for key in keys}


class DataHandler:
    """Extracts metadata for a Kodi ListItem and prepares a normalized dict."""

    def __init__(
        self,
        target: str,
        dbtype: str,
        dbid: str,
    ) -> None:
        """
        Initialize the handler with listitem, dbtype and dbid.

        :param target: InfoLabel prefix (e.g. "Container(3100).ListItem").
        :param dbtype: Database content type (e.g. video or tvshow).
        :param dbid: Database ID for the given item.
        """
        self.target = target
        self.dbtype = dbtype
        self.dbid = dbid
        self.infolabels = get_infolabels(
            self.target,
            [
                "Label",
                "Director",
                "Writer",
                "Genre",
                "Studio",
                "Plot",
                "PlotOutline",
            ],
        )

    def fetch_data(self) -> dict[str, object]:
        """
        Build a normalized metadata dictionary.

        :return: Dictionary with art, resume, contributors, etc.
        """
        label = return_label(self.infolabels["Label"])
        encoded_label = url_encode(label)
        return {
            "file": encoded_label,
            "label": label,
            "label2": label,
            "Directors": split_random(self.infolabels["Director"]),
            "Genres": split_random(self.infolabels["Genre"]),
            "Studios": self._studio(),
            "Writers": split(self.infolabels["Writer"]),
            "Plot": self.infolabels["Plot"],
            "PlotOutline": self.infolabels["PlotOutline"],
        }

    def _studio(self) -> str:
        """
        Returns first studio name, cleaned of '+'.

        :return: Studio string or empty string.
        """
        studio = (
            split(infolabel(f"{self.target}(-1).Studio"))
            if self.dbtype == "set"
            else split(self.infolabels["Studio"])
        )
        return studio.replace("+", "") if studio else ""


class JumpButton:
    """
    Scrollbar thumb indicator with optional sort letter.
    Positioning is fully driven by compute_rect + PlacementOpts.
    """

    def __init__(self, container: str, btn_id: int) -> None:
        """
        Initialize the fraction source and the indicator button id.

        :param container: InfoLabel prefix of the list ("Container" or "Container(id)").
        :param btn_id: Indicator button control ID.
        """

        self.window = Window(getCurrentWindowId())
        self.container = container
        self.btn_id = btn_id

    def _fraction(self) -> float:
        """
        Cursor fraction from CurrentItem / NumItems of the list (1-based, move-synchronous).

        :return: 0.0 at first item, 1.0 at last; 0.0 when fewer than two items.
        """

        cur = to_int(infolabel(f"{self.container}.CurrentItem"), 0)
        total = to_int(infolabel(f"{self.container}.NumItems"), 0)
        return (cur - 1) / (total - 1) if total > 1 else 0.0

    def update(self, *, sortletter: str | None, opts: PlacementOpts) -> None:
        """
        Update indicator label and position along the resolved track.

        :param sortletter: Custom label or fallback to ListItem.SortLetter if None.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/…).
        """
        expected = sortletter or infolabel(f"{self.container}.ListItem.SortLetter")
        fraction = self._fraction()

        rect = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )
        if rect is None:
            return
        posx, posy, width, height = rect

        try:
            btn = self.window.getControl(self.btn_id)
        except RuntimeError:
            log.debug(f"{self.__class__.__name__} → Button {self.btn_id} not found.")
            return

        btn_w = btn.getWidth()
        btn_h = btn.getHeight()
        if not (btn_w and btn_h):
            log.warning(
                f"{self.__class__.__name__} → target_id {self.btn_id} has no size; set width/height in XML"
            )
            return
        horizontal = width >= height

        if horizontal:
            btn_posx = axis_travel(posx, width, btn_w, fraction)
            btn_posy = (
                btn.getY()
                if opts.relative
                else align_y(posy, height, btn_h, opts.valign, opts.vpad)
            )
        else:
            btn_posy = axis_travel(posy, height, btn_h, fraction)
            btn_posx = (
                btn.getX()
                if opts.relative
                else align_x(posx, width, btn_w, opts.halign, opts.hpad)
            )

        btn.setLabel(expected)
        btn.setPosition(btn_posx, btn_posy)
        log.debug(
            f"{self.__class__.__name__} → DONE → "
            f"rect=({posx},{posy},{width},{height}) "
            f"label='{expected}' fraction={fraction:.3f} "
            f"btn=({btn_posx},{btn_posy}) {btn_w}x{btn_h} "
            f"axis={'h' if horizontal else 'v'}"
        )


class ProgressBarManager:
    """
    Calculates playback or set progress for a focused item and
    positions the corresponding progress bar UI elements.
    """

    def __init__(
        self,
        target: str,
        base_id: int,
    ) -> None:
        """
        Initialize default control IDs and sizing.

        :param target: InfoLabel prefix (e.g. "ListItem" or "Container(50).ListItem").
        :param base_id: Base group ID that wraps the bar/btn; sub-controls default to +1/+2/+3.
        """

        self.window = Window(getCurrentWindowId())
        self.target = target
        self.base_id = base_id
        self.progress_id = base_id + 1
        self.btn_id = base_id + 2
        self.img_id = base_id + 3
        self.infolabels = get_infolabels(
            self.target,
            [
                "DBType",
                "PercentPlayed",
                "Property(WatchedEpisodePercent)",
                "Property(WatchedProgress)",
                "Property(UnwatchedEpisodes)",
            ],
        )

    def calculate(self) -> tuple[int, str]:
        """
        Compute percent and unwatched label for the item referenced by ``target``.

        :param set_target: Container id string holding movie set, or None.
        :return: (percent float [0-100], unwatched label as string)
        """

        unwatched = self.infolabels["Property(UnwatchedEpisodes)"]
        for p in [
            self.infolabels["PercentPlayed"],
            self.infolabels["Property(WatchedEpisodePercent)"],
            self.infolabels["Property(WatchedProgress)"],
        ]:
            if p.isdigit() and (resume := int(p)) > 0:
                return resume, unwatched

        if condition(
            f"String.IsEqual({self.target}.Overlay,OverlayWatched.png) | "
            f"Integer.IsGreater({self.target}.PlayCount,0)"
        ):
            return 100, ""

        if self.infolabels["DBType"] == "set":
            set_id = int(infolabel(f"{self.target}.DBID") or 0)
            if not set_id:
                return 0, ""

            response = json_call(
                method="VideoLibrary.GetMovieSetDetails",
                params={
                    "setid": int(set_id),
                    "movies": {"properties": ["playcount"], "limits": {"start": 0}},
                },
                parent=self.__class__.__name__,
            )
            movies = response.get("result", {}).get("setdetails", {}).get("movies", [])

            total = len(movies)
            if not total:
                return 0, ""

            watched = sum(1 for m in movies if m.get("playcount"))
            return (watched / total * 100), (total - watched)

        return 0, unwatched

    def update(
        self,
        percent: float,
        *,
        opts: PlacementOpts,
        progress_id: int | None = None,
        btn_id: int | None = None,
        img_id: int | None = None,
    ) -> None:
        """
        Resolve rect, move/size controls, and position the thumb.

        :param percent: Unified progress percentage (0-100).
        :param opts: Placement options (coords/anchor/inset/track_w/track_h).
        :param progress_id: Optional override for progress bar ID.
        :param btn_id: Optional override for thumb button ID.
        """
        base_id = self.base_id
        progress_id = to_int(progress_id, self.progress_id)
        btn_id = to_int(btn_id, self.btn_id)
        img_id = to_int(img_id, self.img_id)

        try:
            base = self.window.getControl(base_id)
            progress = self.window.getControl(progress_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__} → base_id {base_id} or progress_id {progress_id} not found."
            )
            return

        rect = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )
        if rect is None:
            return
        posx, posy, width, height = rect

        if width <= 0 or height <= 0:
            log.debug(
                f"{self.__class__.__name__} → Zero-size rect → ({posx},{posy},{width},{height}); aborting."
            )
            return

        # Position/sizing
        base.setPosition(posx, posy)
        progress.setWidth(width)
        progress.setHeight(height)

        try:
            img = self.window.getControl(img_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__} → Optional img_id {img_id} not found."
            )
        else:
            img.setWidth(width)
            img.setHeight(height)

        try:
            cur_w, cur_h = base.getWidth(), base.getHeight()
        except Exception:
            cur_w = cur_h = 0

        new_w = max(cur_w or 0, width)
        new_h = max(cur_h or 0, height)
        if new_w != (cur_w or 0) or new_h != (cur_h or 0):
            base.setWidth(new_w)
            base.setHeight(new_h)

        try:
            button = self.window.getControl(btn_id)
        except RuntimeError:
            button = None
            log.debug(
                f"{self.__class__.__name__} → Optional btn_id {btn_id} not found."
            )
        else:
            btn_w, btn_h = button.getWidth(), button.getHeight()
            if not (btn_w and btn_h):
                log.warning(
                    f"{self.__class__.__name__} → btn_id {btn_id} has no size; set width/height in XML"
                )
                button = None

        if button is not None:
            fraction = max(0.0, min(1.0, (percent or 0) / 100.0))
            unwatched_centre = width * (1 + fraction) / 2
            btn_posx = int(max(0, min(unwatched_centre - btn_w / 2, width - btn_w)))
            btn_posy = int((height - btn_h) / 2)
            button.setPosition(btn_posx, btn_posy)
        log.debug(
            f"{self.__class__.__name__} → DONE → "
            f"rect=({posx},{posy},{width},{height}) "
            f"percent={percent} "
            f"btn={'skipped' if button is None else f'({btn_posx},{btn_posy}) {btn_w}x{btn_h}'}"
        )


@lru_cache(maxsize=8)
def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont | None:
    """Load a font via direct path, falling back to a VFS read for
    resource:// and other non-filesystem paths.

    :param font_path: special://, resource://, or absolute font path.
    :param font_size: Font size in skin-coordinate pixels.
    :return: Loaded font, or None if unreadable.
    """
    t0 = time.perf_counter()
    from PIL import ImageFont

    log.debug(f"_load_font → PIL import {(time.perf_counter() - t0) * 1000:.0f}ms")
    try:
        return ImageFont.truetype(xbmcvfs.translatePath(font_path), font_size)
    except OSError:
        pass
    handle = xbmcvfs.File(font_path)
    try:
        data = handle.readBytes()
    finally:
        handle.close()
    if not data:
        log.warning(f"_load_font → unreadable: {font_path}")
        return None
    try:
        return ImageFont.truetype(io.BytesIO(data), font_size)
    except OSError:
        log.warning(f"_load_font → not a valid font: {font_path}")
        return None


def clamp_text(
    *,
    text: str,
    font_path: str,
    font_size: int,
    max_width: int,
    max_lines: int,
) -> str:
    """Clamp text to max_lines when wrapped at max_width with the given font.
    Metric-only: measures glyph advances via FreeType, no GUI roundtrips.

    :param text: Full input string.
    :param font_path: special://, resource://, or absolute font path.
    :param font_size: Font size in skin-coordinate pixels.
    :param max_width: Wrap width in skin-coordinate pixels.
    :param max_lines: Maximum rendered lines to keep.
    :return: Single unwrapped string; Kodi re-wraps it at render time.
    """
    cache = TruncateCacheHandler()
    key = HashManager.short_hash_str(
        "|".join(
            (
                _CLAMP_VERSION,
                font_path,
                str(font_size),
                str(max_width),
                str(max_lines),
                text,
            )
        ),
        length=16,
    )
    if (cached := cache.get_entry(key)) is not None:
        return cached

    font = _load_font(font_path, font_size)
    if font is None:
        return text
    result = " ".join(fit_lines(font, text, max_width, max_lines))
    cache.upsert_entry(key, result)
    return result


class TypewriterAnimation:
    """
    Typewriter text effect with PlacementOpts-driven positioning.
    Height grows per line up to max_lines unless track_h is provided.
    """

    def __init__(
        self,
        control_id: int,
        step_time: float = 0.025,
        default_line_h: int = 30,
        max_lines: int = 3,
    ):
        """
        Initialise the animator with default control id, timing, and sizing.
        Line height must match the rendered font pitch or text will clip.

        :param control_id: Text control id to animate.
        :param step_time: Delay per character (seconds).
        :param default_line_h: Fallback line height (px) when ``opts.track_h`` is unset.
        :param max_lines: Max number of lines the box may grow to.
        """

        self.window = Window(getCurrentWindowId())
        self.control_id = control_id
        self.step_time = step_time
        self.default_line_h = default_line_h
        self.max_lines = max_lines

    @classmethod
    def reset(cls, target_id: int) -> None:
        """
        Supersede any in-flight run and hide the control.
        Stale text is safe: only update() reveals the control, and it clears first.

        :param target_id: Text control id to hide.
        """

        control_id = target_id
        Window(10000).setProperty(f"typewriter_current_{control_id}", "scroll")
        log.execute(f"Control.SetHidden({control_id})")

    def update(
        self,
        *,
        label: str,
        opts: PlacementOpts,
        max_lines: int | None = None,
        start_delay: float = 0,
        alive: Callable[[], bool] | None = None,
    ) -> None:
        """
        Animate label with a typewriter effect using compute_rect placement.
        ``track_h`` must match the rendered font pitch or text will clip.

        :param label: Text to animate.
        :param opts: Placement options; ``track_h`` is line height + growth.
        :param max_lines: Optional cap for number of lines (overrides default).
        :param start_delay: Seconds before typing begins; abort checks apply during the wait.
        :param alive: Optional guard callable; return False to abort animation.
        """
        monitor = Monitor()

        def _alive() -> bool:
            if monitor.abortRequested():
                return False
            return alive() if alive is not None else True

        log.debug(f"{self.__class__.__name__} → START → '{label}'")
        control_id = self.control_id

        # Ownership lease. Isolated typewriter instances share prop
        owner_key = f"typewriter_current_{control_id}"
        my_token = str(time.time_ns())
        home = Window(10000)
        home.setProperty(owner_key, my_token)

        def _superseded() -> bool:
            return home.getProperty(owner_key) != my_token

        if start_delay > 0:
            if monitor.waitForAbort(start_delay):
                return
            if not _alive() or _superseded():
                log.debug(
                    f"{self.__class__.__name__} → ABORTED → '{label}' during start_delay"
                )
                return

        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log.debug(f"{self.__class__.__name__} → Control {control_id} not found")
            return

        def _abort(reason: str) -> None:
            """Clear the control and log why the animation stopped."""
            control.setText("")
            log.debug(f"{self.__class__.__name__} → ABORTED → '{label}' {reason}")

        if not _alive():
            _abort("lost focus")
            return

        line_h = max(1, int(opts.track_h or self.default_line_h))
        max_lines_eff = max_lines or self.max_lines
        max_height = line_h * max_lines_eff

        rect = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
            content_h=(max_height if not opts.track_h else None),
        )
        if rect is None:
            _abort("no rect")
            return
        posx, posy, width, height = rect

        posy_aligned = align_y(posy, height, line_h, align=opts.valign, pad=0)
        posx_final, posy_final, width_final, height_final = (
            posx,
            posy_aligned,
            width,
            line_h,
        )

        if _superseded():
            _abort("superseded")
            return

        control.setWidth(width_final)
        control.setHeight(height_final)
        control.setPosition(posx_final, posy_final)

        if not _alive():
            _abort("lost focus")
            return

        # Animate: add line_h per wrap, up to max_lines
        current_height = line_h
        current_posy = posy_final
        grows = 0

        # Clear before reveal so no render frame shows a stale label.
        control.setText("")
        control.setVisible(True)

        for i in range(1, len(label) + 1):
            if not _alive():
                _abort("lost focus")
                return

            if _superseded():
                _abort("superseded")
                return

            sub = label[:i]
            control.setText(sub)

            # Step wait: paces the animation and, importantly, gives Kodi a
            # render frame to re-layout the new text before HasNext is read.
            if monitor.waitForAbort(self.step_time):
                return

            # Kodi TextBox controls expose Container(id).HasNext when text overflows
            if (
                i > 1
                and condition(f"Container({control_id}).HasNext")
                and current_height < max_height
            ):
                next_h = min(current_height + line_h, max_height)
                dy = next_h - current_height
                current_height = next_h
                grows += 1

                # Shift Y to keep the alignment anchor fixed as height grows.
                v = (opts.valign or "center").lower()
                if v == "bottom":
                    current_posy -= dy
                elif v == "center":
                    current_posy -= dy // 2

                control.setHeight(current_height)
                control.setPosition(posx_final, current_posy)

            # Reflow nudge: append a zero-width space then revert, to force wrap.
            control.setText(sub + "\u200b")
            if monitor.waitForAbort(0.001):
                return
            control.setText(sub)

        log.debug(
            f"{self.__class__.__name__} → DONE → '{label}' "
            f"(len={len(label)} grows={grows} h={current_height}/{max_height} line_h={line_h})"
        )
