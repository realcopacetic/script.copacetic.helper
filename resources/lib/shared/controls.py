# author: realcopacetic

from resources.lib.shared.utilities import Window, infolabel, log, window_property


class ProgressIndicator:
    def __init__(self, window_id=10025, parent_id=4030, button_id=4031):
        self.window_id = window_id
        self.parent_id = parent_id
        self.button_id = button_id
        self.button_width = 30

    def update_position(self, resume_position):
        window = Window(self.window_id)
        try:
            parent = window.getControl(self.parent_id)
            button = window.getControl(self.button_id)
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

        parent_width = parent.getWidth()
        current_y = button.getY()
        button.setPosition(positionX, current_y)


class JumpButton:
    def __init__(self, window_id=10025, scrollbar_id=60, jump_button_id=62):
        self.window_id = window_id
        self.scrollbar_id = scrollbar_id
        self.jump_button_id = jump_button_id
        self.button_width = 30

    def update_position(self, sortletter=None):
        scrollbar_width = 1680
        scrollbar_value = infolabel(f"Control.GetLabel({self.scrollbar_id})")
        if not scrollbar_value:
            return
        try:
            current_item, total_items = map(int, scrollbar_value.split("/"))
        except ValueError as e:
            return
        fraction = current_item / total_items if total_items else 0

        positionX = int((fraction * scrollbar_width) - (self.button_width / 2))
        positionX = max(0, min(positionX, scrollbar_width - self.button_width))

        try:
            window = Window(self.window_id)
            jump_button = window.getControl(self.jump_button_id)
            current_y = jump_button.getY()
            jump_button.setPosition(positionX, current_y)
        except RuntimeError:
            log(
                f"{self.__class__.__name__}: ID {self.jump_button_id} not found in Window {self.window_id}"
            )
            return

        window_property("sort_letter", sortletter or infolabel("ListItem.SortLetter"))
