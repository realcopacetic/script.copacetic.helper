# author: realcopacetic

from resources.lib.shared.utilities import Window, infolabel, log, window_property, xbmc


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
    def __init__(self, window_id=10025, control_id=8760, step_time=0.025):
        self.window = Window(window_id)
        self.control_id = control_id
        self.step_time = step_time

    def start(self, label, year=""):
        expected = f"{label}. {year}." if year else f"{label}."
        log(f"TypewriterLabelManager: START animation: '{expected}'")

        try:
            control = self.window.getControl(self.control_id)
        except Exception:
            log(f"TypewriterLabelManager: Control {self.control_id} not found")
            return

        control.setLabel("")

        for i in range(1, len(expected) + 1):
            # Abort if current focus changed to a different listitem
            current_label = infolabel("ListItem.Label")
            current_year = infolabel("ListItem.Year")
            current_focus = f"{current_label}. {current_year}." if current_year else f"{current_label}."

            if current_focus != expected:
                log("TypewriterLabelManager: Aborted — user focus changed")
                return
            control.setLabel(expected[:i])
            xbmc.sleep(int(self.step_time * 1000))

        log(f"TypewriterLabelManager: DONE animation: '{expected}'")

    def clear(self):
        try:
            control = self.window.getControl(self.control_id)
            control.setLabel("")
        except Exception:
            log(f"TypewriterLabelManager → Control {self.control_id} not found (clear)")
