# author: realcopacetic

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.geometry import (
    PlacementOpts,
    align_x,
    align_y,
    apply_inset,
    axis_travel,
    parse_bool,
    parse_inset,
    resolve_rect,
    to_int,
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
    def __init__(self, listitem, dbtype, dbid):
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

    def _get_infolabels(self, keys):
        return {key: infolabel(f"{self.listitem}.{key}") for key in keys}

    def fetch_data(self):
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

    def _resumepoint(self):
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

    def _studio(self):
        studio = (
            split(infolabel("Container(3100).ListItem(-1).Studio"))
            if "set" in self.dbtype
            else split(self.infolabels["Studio"])
        )
        return studio.replace("+", "") if studio else ""

    def _multiart(self):
        if not (art_type := infolabel("Control.GetLabel(6400)")):
            return {}

        multiart = {
            f"multiart{pos if pos else ''}": art
            for pos in range(16)
            if (
                art := infolabel(f"{self.listitem}.Art({art_type}{pos if pos else ''})")
            )
        }
        return multiart


class JumpButton:
    """
    Displays a scrollbar thumb indicator and optional sort letter overlay.
    Used in alphabet-scrolling lists or fast-seekable UI containers.
    """

    def __init__(self, scroll_id=60, btn_id=62, btn_width=30):
        """
        Initializes the control IDs used for the scrollbar and indicator button.

        :param window_id: Kodi window ID.
        :param scroll_id_id: ID for the scrollbar.
        :param btn_id: ID for the jump button indicator.
        """
        self.window = Window(getCurrentWindowId())
        self.scroll_id = scroll_id
        self.btn_id = btn_id
        self.btn_width = btn_width

    def _fraction_from_scrollbar(self, scroll_id: int) -> float:
        """Compute 0..1 from scrollbar Control.GetLabel(id) formatted as 'cur/total'."""
        raw = infolabel(f"Control.GetLabel({scroll_id})").strip()
        if not raw or "/" not in raw:
            return 0
        try:
            cur, total = map(int, raw.split("/"))
            return (cur / total) if total else 0
        except Exception:
            return 0

    def update(self, *, sortletter: str | None, scroll_id: int, opts: PlacementOpts):
        expected = sortletter or infolabel("ListItem.SortLetter")
        fraction = self._fraction_from_scrollbar(to_int(scroll_id, self.scroll_id))
        posx, posy, width, height = resolve_rect(
            coords=opts.coords,
            window=self.window,
            anchor_id=opts.anchor_id,
            caller_name=self.__class__.__name__,
        )
        posx, posy, width, height = apply_inset(
            (posx, posy, width, height), parse_inset(opts.inset)
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

    def __init__(self, base_id=4030, btn_width=30):
        self.window = Window(getCurrentWindowId())
        self.base_id = base_id
        self.btn_width = btn_width

    def update(
        self, resume_position: int, *, opts: PlacementOpts, base_id: int | None = None
    ):
        """
        Position and size the group based on explicit coords or a parent anchor.
        """
        base_id = to_int(base_id, self.base_id)
        backing_id = base_id + 1
        progress_id = base_id + 2
        btn_id = base_id + 3

        try:
            base = self.window.getControl(base_id)
            backing = self.window.getControl(backing_id)
            progress = self.window.getControl(progress_id)
            button = self.window.getControl(btn_id)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: Controls {base_id}, {backing_id}, {progress_id} or {btn_id} not found"
            )
            return

        posx, posy, width, height = resolve_rect(
            coords=coords,
            window=self.window,
            anchor_id=to_int(anchor_id, None),
            adjust_fn=self._adjust_coords,
            caller_name=self.__class__.__name__,
        )

        base.setPosition(posx, posy)
        for ctrl in (
            base,
            backing,
            progress,
        ):  # Width/height don't inherit from base group
            ctrl.setWidth(width)
            ctrl.setHeight(height)

        min_x = (width / 2) - (self.btn_width / 2)
        max_x = width - (self.btn_width / 2)
        max_limit = width - self.btn_width
        btn_posx = min(
            int(min_x + (resume_position / 100) * (max_x - min_x)), max_limit
        )
        btn_posy = int(0 - (self.btn_width / 2) + (height / 2))
        button.setPosition(btn_posx, btn_posy)


class TypewriterAnimation:
    """
    Animates a text label within a Kodi control using a typewriter effect.
    Progressively reveals given label character-by-character, expanding the
    control's height to accomomdate multiple lines when needed. Will abort
    automatically if focused listitem changes mid-animation.
    """

    def __init__(
        self,
        control_id=8760,
        step_time=0.025,
        line_height=30,
        max_lines=3,
    ):
        """
        :param control_id: Default control ID to animate if none is provided at runtime.
        :param step_time: Delay between adding each character, in seconds.
        :param line_height: Height in pixels to add for each additional line.
        :param max_lines: Maximum number of lines the animation can expand to.
        """
        self.window = Window(getCurrentWindowId())
        self.control_id = control_id
        self.step_time = step_time
        self.line_height = line_height
        self.max_lines = max_lines

    @staticmethod
    def _adjust_coords(coords):
        """
        Adjust control coords to inset and align the animated label.

        :param coords: A tuple of (x, y, width, height) for the control area.
        :return: Adjusted (x, y, width, height) values.
        """
        x, y, w, h = coords
        adjusted_x = x + 15
        adjusted_w = w - 30
        adjusted_h = 37
        adjusted_y = y + h - adjusted_h - 15
        return adjusted_x, adjusted_y, adjusted_w, adjusted_h

    def update(self, label, label_id=None, anchor_id=None, coords="", abort_checker=None):
        """
        Start the typewriter animation for a label.

        :param label: The base label text to animate.
        :param id: Optional override for the control ID.
        :param anchor_id: Optional ID of a parent control to inherit coords from.
        :param coords: Optional comma-separated coords (x,y,w,h).
        """
        log(f"{self.__class__.__name__}: START → '{label}'")
        control_id = to_int(label_id, self.control_id)
        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log(f"{self.__class__.__name__}: Control {control_id} not found")
            return

        posx, posy, width, height = resolve_rect(
            coords=coords,
            window=self.window,
            anchor_id=to_int(anchor_id, None),
            adjust_fn=self._adjust_coords,
            caller_name=self.__class__.__name__,
        )
        current_height = height
        current_posy = posy
        max_height = self.line_height * self.max_lines

        control.setWidth(width)
        control.setHeight(current_height)
        control.setPosition(posx, current_posy)

        timeout, interval, waited = 1000, 50, 0
        while not control.isVisible() and waited < timeout:
            xbmc.sleep(interval)
            waited += interval

        for i in range(1, len(label) + 1):
            if abort_checker != infolabel('Container.CurrentItem'):
                log(f"{self.__class__.__name__}: ABORTED → '{label}' lost focus")
                return

            if (
                i > 1
                and condition(f"Container({control_id}).HasNext")
                and current_height < max_height
            ):
                current_height += self.line_height
                current_posy -= self.line_height
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
