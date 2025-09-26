# author: realcopacetic

from typing import Callable, Iterable

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.geometry import (
    PlacementOpts,
    align_x,
    align_y,
    apply_inset,
    axis_travel,
    parse_inset,
    resolve_rect,
    compute_rect,
)
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    log,
    return_label,
    split,
    split_random,
    to_int,
    url_encode,
    xbmc,
)


class DataHandler:
    """Extracts metadata for a Kodi ListItem and prepares a normalized dict."""

    def __init__(self, listitem: str, dbtype: str, dbid: str) -> None:
        """
        Initialize the handler with listitem, dbtype and dbid.

        :param listitem: Kodi info label prefix (e.g. "ListItem").
        :param dbtype: Kodi database content type.
        :param dbid: Kodi database ID for the item.
        """
        self.listitem = listitem
        self.dbtype = dbtype
        self.dbid = dbid
        self.infolabels = self._get_infolabels(
            [
                "Label",
                "Director",
                "Writer",
                "Genre",
                "Studio",
                "PercentPlayed",
                "Property(WatchedEpisodePercent)",
                "Property(WatchedProgress)",
                "Property(UnwatchedEpisodes)",
            ]
        )
        self.fetched = self.fetch_data()

    def _get_infolabels(self, keys: Iterable[str]) -> dict[str, str]:
        """
        Fetch infolabels for the current listitem.

        :param keys: Iterable of label suffixes.
        :return: Dict mapping suffix → value.
        """
        return {key: infolabel(f"{self.listitem}.{key}") for key in keys}

    def fetch_data(self) -> dict[str, object]:
        """
        Build a normalized metadata dictionary.

        :return: Dictionary with art, resume, contributors, etc.
        """
        label = return_label(self.infolabels["Label"])
        encoded_label = url_encode(label)
        resume, unwatched = self._resumepoint()
        return {
            "file": encoded_label,
            "label": encoded_label,
            "art": self._multiart(),
            "director": split_random(self.infolabels["Director"]),
            "dbtype": self.dbtype,
            "genre": split_random(self.infolabels["Genre"]),
            "resume": {"position": resume, "total": 100},
            "unwatchedepisodes": str(unwatched),
            "studio": self._studio(),
            "writer": split(self.infolabels["Writer"]),
        }

    def _resumepoint(self) -> tuple[int, str]:
        """
        Determine resume percent and unwatched episodes.

        :return: Tuple of (percent, remaining unwatched).
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
            f"String.IsEqual({self.listitem}.Overlay,OverlayWatched.png) | "
            f"Integer.IsGreater({self.listitem}.PlayCount,0)"
        ):
            return 100, ""

        if "set" in self.dbtype:
            total = int(infolabel("Container(3100).NumItems") or 0)
            watched = sum(
                condition(
                    f"Integer.IsGreater(Container(3100).ListItem({x}).PlayCount,0)"
                )
                for x in range(total)
            )
            return ((total and watched / total or 0) * 100), (
                total - watched
            )  # https://stackoverflow.com/a/68118106/21112145 to avoid ZeroDivisionError

        return 0, unwatched

    def _studio(self) -> str:
        """
        Returns first studio name, cleaned of '+'.

        :return: Studio string or empty string.
        """
        studio = (
            split(infolabel("Container(3100).ListItem(-1).Studio"))
            if "set" in self.dbtype
            else split(self.infolabels["Studio"])
        )
        return studio.replace("+", "") if studio else ""

    def _multiart(self) -> dict[str, str]:
        """
        Collect multiart entries based on the active type from label 6400.

        :return: Dict of keys like "fanart", "fanart1", … → art URLs.
        """
        if not (art_type := infolabel("Control.GetLabel(6400)")):
            return {}

        return {
            f"multiart{pos if pos else ''}": art
            for pos in range(16)
            if (
                art := infolabel(f"{self.listitem}.Art({art_type}{pos if pos else ''})")
            )
        }


class JumpButton:
    """
    Scrollbar thumb indicator with optional sort letter.
    Positioning is fully driven by compute_rect + PlacementOpts.
    """

    def __init__(
        self, scroll_id: int = 60, btn_id: int = 62, btn_width: int = 30
    ) -> None:
        """
        Initializes the control IDs used for the scrollbar and indicator button.

        :param scroll_id: Scrollbar control ID to read "cur/total" from.
        :param btn_id: Indicator button control ID to position.
        :param btn_width: Fallback button width/height when control returns 0.
        """
        self.window = Window(getCurrentWindowId())
        self.scroll_id = scroll_id
        self.btn_id = btn_id
        self.btn_width = btn_width

    def _fraction_from_scrollbar(self, scroll_id: int) -> float:
        """
        Compute a 0..1 fraction from Control.GetLabel(scroll_id) formatted as "cur/total".

        :param scroll_id: Scrollbar control ID.
        :return: Fractional position in range [0.0, 1.0], or 0.0 if invalid.
        """
        raw = infolabel(f"Control.GetLabel({scroll_id})").strip()
        if not raw or "/" not in raw:
            return 0
        try:
            cur, total = map(int, raw.split("/"))
            return (cur / total) if total else 0
        except Exception:
            return 0

    def update(
        self, *, sortletter: str | None, scroll_id: int, opts: PlacementOpts
    ) -> None:
        """
        Update indicator label and position along the resolved track.

        :param sortletter: Custom label or fallback to ListItem.SortLetter if None.
        :param scroll_id: Scrollbar control ID override for this update.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/…).
        :return: None
        """
        expected = sortletter or infolabel("ListItem.SortLetter")
        fraction = self._fraction_from_scrollbar(to_int(scroll_id, self.scroll_id))
        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )

        try:
            btn = self.window.getControl(self.btn_id)
        except RuntimeError:
            log(f"{self.__class__.__name__}: Button {self.btn_id} not found.")
            return

        btn_w = btn.getWidth() or self.btn_width
        btn_h = btn.getHeight() or self.btn_width
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
        log(f"{self.__class__.__name__}: UPDATED → '{expected}'")


class ProgressBarManager:
    """
    Displays a seek/resume progress marker on a horizontal bar.
    Calculates X-position based on playback percentage and updates UI control.
    """

    def __init__(
        self,
        base_id: int = 4030,
        btn_width: int = 30,
    ) -> None:
        """
        Initialize default control IDs and sizing.

        :param base_id: Base group ID that wraps the bar/btn.
        :param btn_width: Fallback thumb size if control reports zero.
        """
        self.window = Window(getCurrentWindowId())
        self.base_id = base_id
        self.progress_id = base_id + 1
        self.btn_id = base_id + 2
        self.btn_width = btn_width

    @staticmethod
    def _adjust_coords(
        rect: tuple[int, int, int, int], opts: PlacementOpts
    ) -> tuple[int, int, int, int]:
        """
        Optional inner-track sizing inside the resolved rect (before inset).
        If opts.track_w / track_h are given, center the track accordingly.
        """
        x, y, w, h = rect
        tw = min(opts.track_w or w, w)
        th = min(opts.track_h or h, h)
        if (tw, th) == (w, h):
            return x, y, w, h

        nx = x + (w - tw) // 2
        ny = y + (h - th) // 2
        return nx, ny, tw, th

    def update(
        self,
        percent: int,
        *,
        opts: PlacementOpts,
        base_id: int | None = None,
        progress_id: int | None = None,
        btn_id: int | None = None,
    ) -> None:
        """
        Resolve rect, move/size controls, and position the thumb.

        :param percent: Unified progress percentage (0–100).
        :param opts: Placement options (coords/anchor/inset/track_w/track_h).
        :param base_id: Optional override for base group ID.
        :param progress_id: Optional override for progress bar ID.
        :param btn_id: Optional override for thumb button ID.
        """
        base_id = to_int(base_id, self.base_id)
        progress_id = to_int(progress_id, self.progress_id)
        btn_id = to_int(btn_id, self.btn_id)

        try:
            base = self.window.getControl(base_id)
            progress = self.window.getControl(progress_id)
        except RuntimeError:
            log(f"{self.__class__.__name__}: base_id {base_id} or progress_id {progress_id} not found.")
            return

        # 1) resolve → 2) optional track size → 3) inset
        posx, posy, width, height = resolve_rect(
            coords=opts.coords,
            window=self.window,
            anchor_id=to_int(opts.anchor_id, base_id),
            caller_name=self.__class__.__name__,
        )
        posx, posy, width, height = self._adjust_coords(
            (posx, posy, width, height), opts
        )
        posx, posy, width, height = apply_inset(
            (posx, posy, width, height), parse_inset(opts.inset)
        )

        if width <= 0 or height <= 0:
            log(
                f"{self.__class__.__name__}: Zero-size rect → ({posx},{posy},{width},{height}); aborting."
            )
            return

        # Position/sizing
        base.setPosition(posx, posy)
        for ctrl in (base, progress):
            ctrl.setWidth(width)
            ctrl.setHeight(height)

        try:
            button = self.window.getControl(btn_id)
        except RuntimeError:
            button = None
            log(f"{self.__class__.__name__}: Optional btn_id {btn_id} not found.")
        else:
            btn_w = button.getWidth() or self.btn_width
            btn_h = button.getHeight() or self.btn_width
            travel = max(0, width - btn_w)
            fraction = max(0.0, min(1.0, (percent or 0) / 100.0))
            btn_posx = int(posx + fraction * travel)
            btn_posy = int(posy + (height - btn_h) / 2)
            button.setPosition(btn_posx, btn_posy)


class TypewriterAnimation:
    """
    Typewriter text effect with PlacementOpts-driven positioning.
    Height grows per line up to max_lines unless track_h is provided.
    """

    def __init__(
        self,
        control_id: int = 8760,
        step_time: float = 0.025,
        line_height: int = 30,
        max_lines: int = 3,
    ):
        """
        :param control_id: Default text control id to animate if none is passed.
        :param step_time: Delay per character (seconds).
        :param line_height: Pixels added per wrapped line.
        :param max_lines: Max number of lines grown if track_h not set.
        """
        self.window = Window(getCurrentWindowId())
        self.control_id = control_id
        self.step_time = step_time
        self.line_height = line_height
        self.max_lines = max_lines

    def update(
        self,
        *,
        label: str,
        opts: PlacementOpts,
        label_id: int | None = None,
        anchor_id: int | None = None,
        coords: str = "",
        expected_identity: str | None = None,
        identity_getter: Callable[[], str] | None = None,
    ) -> None:
        """
        Animate label with a typewriter effect using compute_rect placement.

        :param label: Text to animate.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/halign/valign/hpad/vpad).
        :param label_id: Optional override control id.
        :param anchor_id: Legacy anchor (ignored if opts.anchor_id set).
        :param coords: Legacy "x,y,w,h" (ignored if opts.coords set).
        :param expected_identity: Focus snapshot for guarding.
        :param identity_getter: Returns current identity for guard checks.
        :return: None
        """
        def alive() -> bool:
            if identity_getter and expected_identity is not None:
                if not (ok := identity_getter() == expected_identity):
                    log(f"{self.__class__.__name__}: ABORTED → '{label}' lost focus")
                return ok
            return True

        log(f"{self.__class__.__name__}: START → '{label}'")
        control_id = to_int(label_id, self.control_id)

        if not alive():
            return

        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log(f"{self.__class__.__name__}: Control {control_id} not found")
            return

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
            legacy_coords=coords,
            legacy_anchor_id=to_int(anchor_id, None),
            content_h=(self.line_height * self.max_lines) if not opts.track_h else None,
        )

        current_height = height
        current_posy = posy
        max_height = self.line_height * self.max_lines

        control.setWidth(width)
        control.setHeight(current_height)
        control.setPosition(posx, current_posy)

        if not alive():
            return

        timeout, interval, waited = 1000, 50, 0
        while not control.isVisible() and waited < timeout:
            xbmc.sleep(interval)
            waited += interval

        current_height = height
        current_posy = posy
        max_height = self.line_height * self.max_lines if not opts.track_h else height

        for i in range(1, len(label) + 1):
            if not alive():
                return

            if (
                i > 1
                and condition(f"Container({control_id}).HasNext")
                and current_height < max_height
            ):
                current_height += self.line_height
                current_posy -= self.line_height  # keep bottom aligned
                control.setHeight(current_height)
                control.setPosition(posx, current_posy)

            control.setText(label[:i])
            xbmc.sleep(int(self.step_time * 1000))

        log(f"{self.__class__.__name__}: DONE → '{label}'")


class LabelTruncator:
    def __init__(self, window_id=10025, control_id=8860, floor=0, ceiling=None):
        """
        :param window_id: Kodi window ID where the TextBox lives.
        :param control_id: The ID of the TextBox control to truncate.
        :param floor: Minimum number of characters to preserve.
        :param ceiling: Optional upper bound (defaults to full label length).
        """
        self.window = Window(window_id)
        self.control_id = control_id
        self.floor = floor
        self.ceiling = ceiling
        self.ellipsis = "..."

    def truncate(self, text):
        """
        Truncates text to fit inside a TextBox control using binary search.
        Sets the truncated text directly on the control.

        :param text: The original long string.
        :return: The truncated string that was set.
        """
        try:
            control = self.window.getControl(self.control_id)
        except Exception:
            log(f"{self.__class__.__name__}: Control {self.control_id} not found")
            return text

        max_len = self.ceiling or len(text)
        control.setText(text)
        xbmc.sleep(20)
        if not xbmc.getCondVisibility(f"Container({self.control_id}).HasNext"):
            return text

        floor, ceiling = self.floor, max_len
        best_fit = None

        count = 0
        while floor < ceiling:
            count += 1
            mid = (floor + ceiling) // 2
            slice_point = text.rfind(" ", 0, mid)
            if slice_point == -1:
                slice_point = mid
            test = text[:slice_point] + self.ellipsis
            control.setText(test)
            xbmc.sleep(20)
            if xbmc.getCondVisibility(f"Container({self.control_id}).HasNext"):
                ceiling = mid
            else:
                best_fit = slice_point
                floor = mid + 1

        if best_fit is not None:
            final = text[:best_fit] + self.ellipsis
            control.setText(final)
            return final

    def truncate_by_floor(self, text):
        """
        Truncate text at the nearest full word under the floor limit.
        No UI overflow checks — purely character-based.

        :param text: The input string to truncate.
        :return: Truncated string ending at nearest word, with ellipsis.
        """
        try:
            control = self.window.getControl(self.control_id)
        except Exception:
            xbmc.log(
                f"{self.__class__.__name__}: Control {self.control_id} not found",
                xbmc.LOGWARNING,
            )
            return text

        if len(text) <= self.floor:
            return text

        slice_point = text.rfind(" ", 0, self.floor)
        if slice_point == -1:
            slice_point = self.floor  # no space found, hard cut

        final = text[:slice_point].rstrip() + self.ellipsis
        control.setText(final)
        return final
