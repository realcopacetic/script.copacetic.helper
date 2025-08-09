# author: realcopacetic

from resources.lib.shared.utilities import (
    Window,
    condition,
    infolabel,
    log,
    return_label,
    split,
    split_random,
    url_encode,
    window_property,
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
        director = split_random(self.infolabels["Director"])
        writer = split(self.infolabels["Writer"])
        genre = split_random(self.infolabels["Genre"])
        resume, unwatched = self._resumepoint()
        studio = self._studio()
        multiart = self._multiart()
        if "3100" not in self.listitem:
            window_property("url_encoded_label", value=encoded_label)
            window_property("random_genre", value=genre)
            window_property("random_director", value=director)
        return {
            "file": encoded_label,
            "label": encoded_label,
            "art": multiart,
            "director": director,
            "dbtype": self.dbtype,
            "genre": genre,
            "resume": {"position": resume, "total": 100},
            "unwatchedepisodes": str(unwatched),
            "studio": studio,
            "writer": writer,
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

        return {
            f"multiart{pos if pos else ''}": art
            for pos in range(16)
            if (
                art := infolabel(f"{self.listitem}.Art({art_type}{pos if pos else ''})")
            )
        }


class ProgressIndicator:
    """
    Displays a seek/resume progress marker on a horizontal bar.
    Calculates X-position based on playback percentage and updates UI control.
    """

    def __init__(self, window_id=10025, parent_id=4030, button_id=4031):
        """
        Initializes the progress indicator control IDs and layout.

        :param window_id: Kodi window ID where the controls exist.
        :param parent_id: Control ID for the progress bar parent.
        :param button_id: Control ID for the movable indicator.
        """
        self.window = Window(window_id)
        self.parent_id = parent_id
        self.button_id = button_id
        self.button_width = 30

    def update_position(self, resume_position):
        """
        Calculates the new X-position and updates the button to reflect progress.

        :param resume_position: Float or int representing percent viewed.
        """
        try:
            parent = self.window.getControl(self.parent_id)
            button = self.window.getControl(self.button_id)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: IDs {self.parent_id}, {self.button_id} not found in Window {self.window_id}"
            )
            return
        parent_width = parent.getWidth()
        self.minX = (parent_width / 2) - (
            self.button_width / 2
        )  # Min position when resume = 0%)
        self.maxX = parent_width - (
            self.button_width / 2
        )  # Max position when resume = 100%
        self.max_limit = (
            parent_width - self.button_width
        )  # Ensure button position does not exceed edge of parent control

        positionX = int(self.minX + (resume_position / 100) * (self.maxX - self.minX))
        positionX = min(positionX, self.max_limit)

        current_y = button.getY()
        button.setPosition(positionX, current_y)


class JumpButton:
    """
    Displays a scrollbar thumb indicator and optional sort letter overlay.
    Used in alphabet-scrolling lists or fast-seekable UI containers.
    """

    def __init__(self, window_id=10025, scrollbar_id=60, jump_button_id=62):
        """
        Initializes the control IDs used for the scrollbar and indicator button.

        :param window_id: Kodi window ID.
        :param scrollbar_id: ID for the label-style scrollbar (e.g. "12/58").
        :param jump_button_id: ID for the jump button indicator.
        """
        self.window = Window(window_id)
        self.scrollbar_id = scrollbar_id
        self.jump_button_id = jump_button_id
        self.button_width = 30

    def update_position(self, sortletter=None):
        """
        Updates the position of the jump button based on scrollbar progress.

        :param sortletter: Optional sort letter (e.g., "A", "B") to display.
        :returns: None
        """
        current_letter = sortletter or infolabel("ListItem.SortLetter")
        if current_letter != infolabel("ListItem.SortLetter"):
            log(f"{self.__class__.__name__}: ABORTED → '{current_letter}' stale")
            return

        try:
            jump_button = self.window.getControl(self.jump_button_id)
            current_y = jump_button.getY()
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: ID {self.jump_button_id} not found in Window {self.window_id}"
            )
            return

        scrollbar_width = 1680
        scrollbar_value = infolabel(f"Control.GetLabel({self.scrollbar_id})")
        if not scrollbar_value:
            return

        try:
            current_item, total_items = map(int, scrollbar_value.split("/"))
        except ValueError as e:
            log(f"{self.__class__.__name__}: Error parsing scrollbar value → {e}")
            return

        fraction = current_item / total_items if total_items else 0
        positionX = int((fraction * scrollbar_width) - (self.button_width / 2))
        newX = max(0, min(positionX, scrollbar_width - self.button_width))

        if current_letter != infolabel("ListItem.SortLetter"):
            log(f"{self.__class__.__name__}: ABORTED → '{current_letter}' stale")
            return

        jump_button.setLabel(current_letter)
        jump_button.setPosition(newX, current_y)
        log(f"{self.__class__.__name__}: UPDATED → '{current_letter}'")


class TypewriterAnimation:
    def __init__(self, window_id=10025, control_id=8760, step_time=0.025):
        self.window = Window(window_id)
        self.control_id = control_id
        self.step_time = step_time

    def start(self, label, year=""):
        expected = f"{label}. {year}." if year else f"{label}."
        log(f"{self.__class__.__name__}: START → '{expected}'")

        try:
            control = self.window.getControl(self.control_id)
        except Exception:
            log(f"{self.__class__.__name__}: Control {self.control_id} not found")
            return

        timeout = 1000  # max wait 1000ms
        interval = 50  # check every 50ms
        waited = 0
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

            control.setLabel(expected[:i])
            xbmc.sleep(int(self.step_time * 1000))

        log(f"{self.__class__.__name__}: DONE → '{expected}'")

    def clear(self):
        try:
            control = self.window.getControl(self.control_id)
            control.setLabel("")
            log(f"{self.__class__.__name__}: CLEARED")
        except Exception:
            log(
                f"{self.__class__.__name__}: Control {self.control_id} not found (clear)"
            )

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
            xbmc.log(
                f"{self.__class__.__name__}: Control {self.control_id} not found",
                xbmc.LOGWARNING,
            )
            return text

        max_len = self.ceiling or len(text)
        control.setText(text)
        xbmc.sleep(20)
        if not xbmc.getCondVisibility(f"Container({self.control_id}).HasNext"):
            return text

        floor, ceiling = self.floor, max_len
        best_fit = None

        count=0
        while floor < ceiling:
            count += 1
            log(f'FUCK DEBUG {count}')
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
            log(f"FUCK DEBUG final length {len(final)}")
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
