# author: realcopacetic
from xbmcgui import Window, getCurrentWindowId

from resources.lib.shared.utilities import (
    condition,
    infolabel,
    log,
    return_label,
    split,
    split_random,
    url_encode,
    xbmc,
)

DEFAULT_COORDS = {
    "TypewriterAnimation": (0, 0, 1920, 1080),
    "ProgressBarManager": (780, 1050, 360, 4),
}


def parse_coords(
    coords, window, anchor_id=None, adjust_fn=None, caller_name=None
):
    """
    Attempts to parse coords from string or fallback to anchor_id control.
    Then optionally adjusts the result using a class-specific function.

    :param coords: Comma-separated coords (x,y,w,h).
    :param window: Kodi window object containing the controls.
    :param anchor_id: ID of a parent control to query if coords are missing.
    :param adjust_fn: Optional function to adjust the coordinate tuple.
    :param caller_name: Optional string to prefix in log messages.
    :return: A tuple of (x, y, width, height), or DEFAULT_COORDS on failure.
    """
    caller = caller_name or __name__

    if coords:
        try:
            coords = tuple(map(int, coords.split(",")))
            return coords
        except Exception as e:
            log(f"{caller}: Invalid coords '{coords}': {e}")

    if anchor_id:
        try:
            a = window.getControl(anchor_id)
            coords = (
                a.getX(),
                a.getY(),
                a.getWidth(),
                a.getHeight(),
            )
            return adjust_fn(coords) if adjust_fn else coords
        except Exception as e:
            log(f"{caller}: Failed to get parent ({anchor_id}) dimensions: {e}")

    return DEFAULT_COORDS.get(caller, (0, 0, 0, 0))


def to_int(value, default=None):
    """
    Safely convert a value to an integer, returning a default on failure.

    :param value: The value to convert.
    :param default: Value to return if conversion fails.
    :return: The converted integer or the default value.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

    def __init__(self, scrollbar_id=60, jump_button_id=62, button_width=30):
        """
        Initializes the control IDs used for the scrollbar and indicator button.

        :param window_id: Kodi window ID.
        :param scrollbar_id: ID for the scrollbar.
        :param jump_button_id: ID for the jump button indicator.
        """
        self.window = Window(getCurrentWindowId())
        self.scrollbar_id = scrollbar_id
        self.button_id = jump_button_id
        self.button_width = button_width

    def update(self, sortletter=None, anchor_id=None):
        """
        Updates the position of the jump button based on scrollbar progress.

        :param sortletter: Optional letter passed as param to display.
        :param coords: Optional 'x,y,w,h' override from plugin params.
        :returns: None
        """
        expected = sortletter or infolabel("ListItem.SortLetter")
        if expected != infolabel("ListItem.SortLetter"):
            log(f"{self.__class__.__name__}: ABORTED → '{expected}' stale")
            return

        if not (raw := infolabel(f"Control.GetLabel({self.scrollbar_id})")):
            return

        try:
            current, total = map(int, raw.split("/"))
            fraction = total and current / total or 0
        except ValueError as e:
            log(f"{self.__class__.__name__}: Error parsing scrollbar value → {e}")
            return

        posx, posy, width, height = parse_coords(
            coords="",
            window=self.window,
            anchor_id=to_int(anchor_id, self.scrollbar_id),
            caller_name="JumpButton",
        )

        try:
            btn = self.window.getControl(self.button_id)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: Jump button {self.button_id} not found."
            )
            return

        if expected != infolabel("ListItem.SortLetter"):
            log(f"{self.__class__.__name__}: ABORTED → '{expected}' stale")
            return

        orientation = "horizontal" if (width >= height) else "vertical"
        travel = max(
            0, (width if orientation == "horizontal" else height) - self.button_width
        )
        if orientation == "horizontal":
            btn_posx = posx + int(fraction * travel)
            btn_posy = int(posy + (height / 2) - (self.button_width / 2))
        else:
            btn_posx = int(posx + (width / 2) - (self.button_width / 2))
            btn_posy = posy + int(fraction * travel)

        btn.setLabel(expected)
        btn.setPosition(btn_posx, btn_posy)
        log(f"{self.__class__.__name__}: UPDATED → '{expected}'")


class ProgressBarManager:
    """
    Displays a seek/resume progress marker on a horizontal bar.
    Calculates X-position based on playback percentage and updates UI control.
    """

    def __init__(self, base_id=4030, button_width=30):
        self.window = Window(getCurrentWindowId())
        self.base_id = base_id
        self.button_width = button_width

    @staticmethod
    def _adjust_coords(coords):
        """
        Adjust control coords to inset and align progress bar controls.
        """
        x, y, w, h = coords
        bar_w = 360 if w >= 360 else 240
        center_x = x + (w // 2)
        pos_x = int(center_x - (bar_w // 2))
        return pos_x, 1050, bar_w, 4

    def update(self, resume_position, base_id=None, anchor_id=None, coords=""):
        """
        Position and size the group based on explicit coords or a parent anchor.
        """
        base_id = to_int(base_id, self.base_id)
        backing_id = base_id + 1
        progress_id = base_id + 2
        button_id = base_id + 3

        try:
            base = self.window.getControl(base_id)
            backing = self.window.getControl(backing_id)
            progress = self.window.getControl(progress_id)
            button = self.window.getControl(button_id)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: Controls {base_id}, {backing_id}, {progress_id} or {button_id} not found"
            )
            return

        posx, posy, width, height = parse_coords(
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

        min_x = (width / 2) - (self.button_width / 2)
        max_x = width - (self.button_width / 2)
        max_limit = width - self.button_width
        button_posx = int(min_x + (resume_position / 100) * (max_x - min_x))
        button_posx = min(button_posx, max_limit)
        button_posy = int(0 - (self.button_width / 2) + (height / 2))
        button.setPosition(button_posx, button_posy)


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

    def update(self, label, year="", label_id=None, anchor_id=None, coords=""):
        """
        Start the typewriter animation for a label.

        :param label: The base label text to animate.
        :param year: Optional year to append to the label.
        :param id: Optional override for the control ID.
        :param anchor_id: Optional ID of a parent control to inherit coords from.
        :param coords: Optional comma-separated coords (x,y,w,h).
        """
        expected = f"{label}. {year}." if year else f"{label}."
        log(f"{self.__class__.__name__}: START → '{expected}'")
        control_id = to_int(label_id, self.control_id)
        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log(f"{self.__class__.__name__}: Control {control_id} not found")
            return

        posx, posy, width, height = parse_coords(
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

        for i in range(1, len(expected) + 1):
            current_label = infolabel("ListItem.Label")
            current_year = infolabel("ListItem.Year")
            current_focus = (
                f"{current_label}. {current_year}."
                if current_year
                else f"{current_label}."
            )
            if current_focus != expected:
                log(f"{self.__class__.__name__}: ABORTED → '{expected}' lost focus")
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

            control.setText(expected[:i])
            xbmc.sleep(int(self.step_time * 1000))

        log(f"{self.__class__.__name__}: DONE → '{expected}'")


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
