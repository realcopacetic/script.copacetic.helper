# author: realcopacetic

import time

from resources.lib.shared.utilities import Window, infolabel, log, window_property


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

        :param sortletter: Optional sort letter (e.g., "A", "B") to display as property.
        :returns: None
        """
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
        positionX = max(0, min(positionX, scrollbar_width - self.button_width))

        try:
            jump_button = self.window.getControl(self.jump_button_id)
            current_y = jump_button.getY()
            jump_button.setPosition(positionX, current_y)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: ID {self.jump_button_id} not found in Window {self.window_id}"
            )
            return

        window_property(
            "sort_letter", value=sortletter or infolabel("ListItem.SortLetter")
        )


class TypewriterLabelManager:
    def __init__(
        self,
        window_id=10025,
        control_id=8760,
        start_delay=0.5,
        step_interval=0.025,
        idle_interval=1.0,
    ):
        """
        :param window_id: Kodi window ID containing the label control.
        :param control_id: ID of the label control to animate.
        :param start_delay: Time (in seconds) to wait before typing begins after a label change.
        :param step_interval: Time between each character update during animation.
        :param idle_interval: Time to wait when animation is idle or complete.
        """
        self.window = Window(window_id)
        self.control_id = control_id
        self.control = None

        self.last_label = ""
        self.target = ""
        self.index = 0
        self.start_time = 0

        self.start_delay = start_delay
        self.step_interval = step_interval
        self.idle_interval = idle_interval

        self.state = "IDLE"  # IDLE, WAITING_FOR_CONTROL, WAITING_TO_START, TYPING, DONE

    def update(self):
        label = infolabel("ListItem.Label")
        year = infolabel("ListItem.Year")
        current_label = f"{label}. {year}." if year else f"{label}."

        if current_label and current_label != self.last_label:
            self.last_label = current_label
            self.target = current_label
            self.index = 0
            self.start_time = time.time() + self.start_delay
            self.state = "WAITING_FOR_CONTROL"

    def step(self):
        if self.state in ("IDLE", "DONE") or not self.target:
            return False

        if self.state == "WAITING_FOR_CONTROL":
            try:
                self.control = self.window.getControl(self.control_id)
                self.state = "WAITING_TO_START"
            except Exception:
                log(
                    f"{self.__class__.__name__}: Control {self.control_id} not found, retrying..."
                )
                return True  # Try again next cycle
            return True

        if self.state == "WAITING_TO_START":
            if time.time() >= self.start_time:
                self.state = "TYPING"
            return True

        if self.state == "TYPING":
            if self.control and self.index <= len(self.target):
                self.control.setLabel(self.target[: self.index])
                self.index += 1
                return True
            self.state = "DONE"
            return False

        return False

    def get_sleep_time(self):
        """
        Returns the appropriate sleep duration based on current animation state.
        """
        if self.state in ("TYPING", "WAITING_TO_START", "WAITING_FOR_CONTROL"):
            return self.step_interval
        return self.idle_interval
