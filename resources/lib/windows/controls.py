# author: realcopacetic

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import (
    condition,
    execute,
    infolabel,
    log,
    skin_string,
    toggle_bool,
)


def set_instance_labels(link, control, instance, skinsettings):
    """
    Applies label and label2 to a control instance, checking link first, then control.
    If label2 is missing, falls back to the current value of the linked skin string.
    """
    setting_id = (link or {}).get("linked_setting")
    fallback = skinsettings.get(setting_id, {}).get("items")
    label = (link or {}).get("label") or control.get("label")
    label2 = (
        (link or {}).get("label2")
        or control.get("label2")
        or (
            value.capitalize()
            if (value := infolabel(f"Skin.String({setting_id})"))
            else ""
        )
        or (
            fallback[0].capitalize() if fallback else ""
        )
    )

    if label or label2:
        instance.setLabel(label=label or "", label2=label2 or "")


class BaseControlHandler:
    def __init__(self, control, instance, skinsettings):
        self.control = control
        self.instance = instance
        self.skinsettings = skinsettings
        self.rule_engine = RuleEngine()

    def update_visibility(self, current_content):
        link = self._find_link(current_content)
        visible_condition = link.get("visible", "") if link else self.control.get("visible", "")

        setting_id = link["linked_setting"]
        setting_values = self.skinsettings.get(setting_id, {}).get("items", [])
        if setting_values:
            current_value = infolabel(f"Skin.String({setting_id})")

        log(f'FUCK DEBUG current_value {current_value}')
        log(f'FUCK DEBUG visible_condition {visible_condition}')
        is_visible = (
            self.rule_engine.evaluate(visible_condition, runtime=True) if visible_condition else True
        )
        log(f"FUCK DEBUG is_visible {is_visible}")
        self.instance.setVisible(is_visible)
        return link

    def _find_link(self, current_content):
        expected_trigger = f"focused({current_content})"
        for link in self.control.get("dynamic_linking", []):
            if link.get("update_trigger") == expected_trigger:
                return link
        return None


class RadioButtonHandler(BaseControlHandler):
    def update_visibility(self, current_content):
        link = super().update_visibility(current_content)
        set_instance_labels(link, self.control, self.instance, self.skinsettings)

    def update_value(self, current_content):
        link = self._find_link(current_content)
        if not link:
            return

        setting_id = link["linked_setting"]
        values = self.skinsettings.get(setting_id, {}).get("items", [])

        is_selected = condition(f"Skin.HasSetting({setting_id})")
        self.instance.setSelected(is_selected)
        self.instance.setEnabled(len(values) > 1)

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        from xbmcgui import ACTION_SELECT_ITEM

        if focused_control_id != self.instance.getId():
            return

        if a_id != ACTION_SELECT_ITEM:
            return

        link = self._find_link(current_content)
        if not link:
            return

        setting_id = link["linked_setting"]
        values = self.skinsettings.get(setting_id, {}).get("items", [])

        if "true" in values and "false" in values:
            toggle_bool(setting_id)


class SliderHandler(BaseControlHandler):
    def update_value(self, current_content):
        link = self._find_link(current_content)
        if not link:
            return

        setting_id = link["linked_setting"]
        setting_values = self.skinsettings.get(setting_id, {}).get("items", [])
        if setting_values:
            current_value = infolabel(f"Skin.String({setting_id})")
            try:
                index = setting_values.index(current_value)
            except ValueError:
                index = 0
            self.instance.setInt(index, 0, 1, len(setting_values) - 1)
        self.instance.setEnabled(len(setting_values) > 1)

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        from xbmcgui import ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT

        if a_id not in (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT):
            return

        index = self.instance.getInt()
        link = self._find_link(current_content)
        if not link:
            return

        setting_id = link["linked_setting"]
        values = self.skinsettings.get(setting_id, {}).get("items", [])

        if 0 <= index < len(values):
            skin_string(setting_id, values[index])


class SliderExHandler(SliderHandler):
    def __init__(self, control, slider_instance, button_instance, skinsettings):
        super().__init__(control, slider_instance, skinsettings)
        self.button_instance = button_instance

    def update_visibility(self, current_content):
        link = super().update_visibility(current_content)
        set_instance_labels(link, self.control, self.button_instance, self.skinsettings)

    def handle_interaction(self, current_content, a_id, focused_control_id=None):
        from xbmcgui import ACTION_SELECT_ITEM

        if self._on_button_focused(focused_control_id):
            if a_id == ACTION_SELECT_ITEM:
                self._focus_slider()
        elif self._on_slider_focused(focused_control_id):
            if a_id == ACTION_SELECT_ITEM:
                self._focus_button()
            else:
                super().handle_interaction(current_content, a_id)

    def _on_button_focused(self, focused_id):
        return self.button_instance.getId() == focused_id

    def _on_slider_focused(self, focused_id):
        return self.instance.getId() == focused_id

    def _focus_button(self):
        execute(f"Control.SetFocus({self.button_instance.getId()})")

    def _focus_slider(self):
        execute(f"Control.SetFocus({self.instance.getId()})")
