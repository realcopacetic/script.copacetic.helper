# author: realcopacetic

import re

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import (
    infolabel,
    log,
    skin_string,
)

COLOR_KEYS = {
    "textcolor": "textColor",
    "focusedcolor": "focusedColor",
    "disabledcolor": "disabledColor",
    "shadowcolor": "shadowColor",
}

def resolve_colour(value):
    info_match = re.match(r"\$INFO\[(.*?)\]", value)
    if info_match:
        resolved = infolabel(info_match.group(1)).strip()
        return f"0x{resolved}"
    else:
        return f"0x{value}"


class BaseControlHandler:
    """
    Base handler class for dynamic Kodi skin controls.
    Manages visibility, config references, and dynamic linking.
    """

    def __init__(self, control, instance, configs, runtime_manager):
        """
        :param control: Dictionary defining control from JSON.
        :param instance: Kodi GUI control instance.
        :param configs: Mapping of configs.
        """
        self.control = control
        self.instance = instance
        self.configs = configs
        self.runtime_manager = runtime_manager
        self.description = control.get("description")
        self.rule_engine = RuleEngine()

    def request_focus_change(self, target_id):
        self.focus_target_id = target_id

    def get_setting_value(self, setting_id):
        config = self.configs.get(setting_id, {})
        storage = config.get("storage", "skinstring")
        default = config.get("default", "")
        if storage == "runtimejson":
            return next(
                (item.get("value", "") for item in self.runtime_manager.runtime_state.get(setting_id, []) if item.get("value")),
                default
            )
        value = infolabel(f"Skin.String({setting_id})").strip()
        return value or default

    def set_setting_value(self, setting_id, value):
        storage = self.configs.get(setting_id, {}).get("storage", "skinstring")
        if storage == "runtimejson":
            for item in self.runtime_manager.runtime_state.get(setting_id, []):
                item["value"] = value
            self.runtime_manager.runtime_state_handler.write_json(self.runtime_manager.runtime_state)
        else:
            skin_string(setting_id, value)

    def update_visibility(self, current_content, focused_control_id):
        """
        Evaluates and sets visibility based on the control's visible condition.
        """
        link = self.get_active_link(current_content)
        visible_condition = (
            link.get("visible", "") if link else self.control.get("visible", "")
        )

        is_visible = (
            self.rule_engine.evaluate(visible_condition, runtime=True)
            if visible_condition
            else True
        )

        self.instance.setVisible(is_visible)

    def get_active_link(self, current_content):
        """
        Return the dynamic_linking entry that matches the currently focused static control.

        :param current_content: Currently focused control ID (e.g., 'movies_button').
        :return: Matching dynamic_link dictionary, or empty dict if no match.
        """
        trigger = f"focused({current_content})"
        return next(
            (
                link
                for link in self.control.get("dynamic_linking", [])
                if link.get("update_trigger") == trigger
            ),
            {},
        )

    def setting_id(self, current_content):
        """
        Return the linked_config ID for the currently matched dynamic link.

        :param current_content: Currently focused control ID.
        :return: config ID string or None.
        """
        return self.get_active_link(current_content).get("linked_config")

    def set_instance_labels(self, link, instance, focused_control_id):
        setting_id = (link or {}).get("linked_config")
        fallback = self.configs.get(setting_id, {}).get("items")
        label = (link or {}).get("label") or self.control.get("label")
        current_value = self.get_setting_value(setting_id)
        label2 = (
            (link or {}).get("label2")
            or self.control.get("label2")
            or (current_value.capitalize() if current_value else "")
        )
        colors = {
            param_name: resolve_colour(self.control[color_key])
            for color_key, param_name in COLOR_KEYS.items()
            if self.control.get(color_key)
        }
        if focused_control_id != instance.getId() and (color := colors.get("textColor")):
            label2 = f"[COLOR {color}]{label2}[/COLOR]"
        if label or label2:
            instance.setLabel(label=label or "", label2=label2 or "", **colors)


class ButtonHandler(BaseControlHandler):
    """
    Empty ButtonHandler class so that BaseControlHandler can pass associated
    description labels for buttons.
    """

    def update_value(self, current_content): ...

    def handle_interaction(self, current_content, a_id, focused_control_id=None): ...


class RadioButtonHandler(BaseControlHandler):
    """
    Handles interactions and updates for radiobutton controls.
    """

    def update_visibility(self, current_content, focused_control_id):
        """
        Sets visibility and label/label2 for the radiobutton control.
        """
        super().update_visibility(current_content, focused_control_id)
        self.set_instance_labels(
            link=self.get_active_link(current_content),
            instance=self.instance,
            focused_control_id=focused_control_id,
        )

    def update_value(self, current_content):
        """
        Updates the selected state and enabled status of the radio control.

        :param current_content: Currently focused static control ID.
        """
        if not (setting_id := self.setting_id(current_content)):
            return

        values = self.configs.get(setting_id, {}).get("items", ["false", "true"])
        log(f"FUCK DBEUG update_value values {values}")
        current_value = self.get_setting_value(setting_id)
        log(f"FUCK DBEUG update_value current_value {current_value}")
        is_selected = current_value == "true"

        self.instance.setSelected(is_selected)
        self.instance.setEnabled(len(values) > 1)

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        """
        Toggles the boolean setting if user selects the radiobutton.

        :param a_id: Kodi action ID.
        :param focused_control_id: ID of currently focused control.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or not (setting_id := self.setting_id(current_content))
        ):
            return

        new_value = "true" if self.instance.isSelected() else "false"

        self.set_setting_value(setting_id, new_value)


class SliderHandler(BaseControlHandler):
    """
    Handles slider controls mapped to a multi-option config.
    """

    def update_value(self, current_content):
        """
        Updates the slider to reflect the current config value.

        :param current_content: Currently focused static control ID.
        """
        if not (setting_id := self.setting_id(current_content)):
            return False

        setting_values = self.configs.get(setting_id, {}).get("items", [])

        if setting_values:
            current_value = self.get_setting_value(setting_id)
            try:
                index = setting_values.index(current_value)
            except ValueError:
                index = 0
            self.instance.setInt(index, 0, 1, len(setting_values) - 1)
        enabled = len(setting_values) > 1
        self.instance.setEnabled(enabled)
        return enabled

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        """
        Updates the skin string when the user interacts with the slider.

        :param a_id: Kodi action (left/right).
        :param focused_control_id: Currently focused control.
        """
        from xbmcgui import ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT

        if (
            focused_control_id != self.instance.getId()
            or a_id
            not in (
                ACTION_MOVE_LEFT,
                ACTION_MOVE_RIGHT,
            )
            or not (setting_id := self.setting_id(current_content))
        ):
            return

        values = self.configs.get(setting_id, {}).get("items", [])
        index = self.instance.getInt()

        if 0 <= index < len(values):
            self.set_setting_value(setting_id, values[index])


class SliderExHandler(SliderHandler):
    """
    Handles sliderex controls composed of a slider and a button.
    Allows toggling focus between the slider and associated button.
    """

    def __init__(self, control, slider_instance, button_instance, configs, runtime_manager):
        """
        :param control: Control definition.
        :param slider_instance: Main slider control instance.
        :param button_instance: Associated label button control.
        :param configs: config mappings.
        """
        super().__init__(control, slider_instance, configs, runtime_manager)
        self.button_instance = button_instance
        self.button_id = button_instance.getId()

    def update_visibility(self, current_content, focused_control_id):
        """
        Updates slider visibility and updates the button's label/label2.
        """
        super().update_visibility(current_content, focused_control_id)
        self.set_instance_labels(
            link=self.get_active_link(current_content),
            instance=self.button_instance,
            focused_control_id=focused_control_id,
        )

    def update_value(self, current_content):
        """
        Passes slider update from parent class then enables/disables button accordingly.

        :param current_content: Currently focused static control ID.
        """
        enabled = super().update_value(current_content)
        self.button_instance.setEnabled(enabled)

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        """
        Handles focus toggle or delegates to slider handler based on action.

        :param a_id: Kodi action ID.
        :param focused_control_id: Currently focused control ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        if a_id == ACTION_SELECT_ITEM:
            if self._on_button_focused(focused_control_id):
                self.request_focus_change(self.instance.getId())
            elif self._on_slider_focused(focused_control_id):
                self.request_focus_change(self.button_instance.getId())
        else:
            super().handle_interaction(current_content, a_id, focused_control_id)

    def _on_button_focused(self, focused_id):
        """
        :return: True if button is focused.
        """
        return self.button_instance.getId() == focused_id

    def _on_slider_focused(self, focused_id):
        """
        :return: True if slider is focused.
        """
        return self.instance.getId() == focused_id
