# author: realcopacetic

import re

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import infolabel, log, skin_string
from resources.lib.windows.onclick_actions import OnClickActions

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

    def __init__(self, control, instance, runtime_manager):
        """
        :param control: Dictionary defining control from JSON.
        :param instance: Kodi GUI control instance.
        """
        self.control = control
        self.instance = instance
        self.runtime_manager = runtime_manager
        self.description = control.get("description")
        self.rule_engine = RuleEngine()
        self.current_listitem = None
        self.container_position = None

    def _get_active_link(self):
        """
        Return the dynamic_linking entry that matches the currently focused static control.

        :return: Matching dynamic_link dictionary, or empty dict if no match.
        """
        trigger = f"focused({self.current_listitem})"

        if self.control.get("expansion") == "runtimejson":
            mapping_key = self.control["mapping"]
            current_value = self.runtime_manager.get_runtime_setting(
                mapping_key,
                self.container_position,
                "mapping_item",
            )
            schema = self.runtime_manager.mappings[mapping_key].get(
                "user_defined_schema", {}
            )
            config_fields = schema.get("config_fields", {})
            field = self.control.get("field")
            template = config_fields.get(field)
            if template:
                placeholders = self.runtime_manager.mappings[mapping_key].get(
                    "placeholders", {}
                )
                return {
                    "update_trigger": trigger,
                    "linked_config": template.format(
                        **{ph_name: current_value for ph_name in placeholders.values()}
                    ),
                }

        return next(
            (
                link
                for link in self.control.get("dynamic_linking", [])
                if link.get("update_trigger") == trigger
            ),
            {},
        )

    def _linked_config(self):
        """
        Return the linked_config ID for the currently matched dynamic link.

        :return: config ID string or None.
        """
        return self._get_active_link().get("linked_config")

    def _allowed_items(self):
        """
        Return the list of values this control may choose from:

        :returns: List of approved string values.
        """
        if config := self._linked_config():
            return self.runtime_manager.configs_data.get(config, {}).get("items", [])
        mapping_key = self.control["mapping"]
        return self.runtime_manager.mappings.get(mapping_key, {}).get("items", [])

    def _get_setting_value(self):
        """
        Return the current value for this control at the given list index.
        First checks for linked_config then falls back to mapping items.

        :returns: The current setting or mapping_item value, or None.
        """
        link = self._get_active_link()

        if cfg := link.get("linked_config"):
            cfg_data = self.runtime_manager.configs_data.get(cfg, {})
            storage = cfg_data.get("storage", "skinstring")
            default = cfg_data.get("default", "")

            if storage == "runtimejson":
                mapping_key = self.control.get("mapping")
                field_name = self.control.get("field")
                try:
                    return self.runtime_manager.get_runtime_setting(
                        mapping_key, self.container_position, field_name
                    )
                except (IndexError, KeyError):
                    return default

            val = infolabel(f"Skin.String({cfg})").strip()
            return val or default

        mapping_key = self.control["mapping"]
        try:
            return self.runtime_manager.get_runtime_setting(
                mapping_key, self.container_position, "mapping_item"
            )

        except (IndexError, KeyError):
            default_order = self.runtime_manager.mappings.get(mapping_key, {}).get(
                "default_order", []
            )
            if 0 <= self.container_position < len(default_order):
                return default_order[self.container_position]

        return None

    def _set_setting_value(self, value):
        """
        Set a new value for this control at the given list index.

        :param value: The new value to store.
        """
        link = self._get_active_link()
        if cfg := link.get("linked_config"):
            cfg_data = self.runtime_manager.configs_data.get(cfg, {})
            storage = cfg_data.get("storage", "skinstring")

            if storage == "runtimejson":
                mapping_key = self.control.get("mapping")
                field_name = self.control.get("field")
                try:
                    self.runtime_manager.update_runtime_setting(
                        mapping_key, self.container_position, field_name, value
                    )
                except IndexError:
                    pass
            else:
                skin_string(cfg, value)
            return

        mapping_key = self.control["mapping"]
        try:
            self.runtime_manager.update_runtime_setting(
                mapping_key, self.container_position, "mapping_item", value
            )
        except IndexError:
            pass
        return

    def _apply_metadata(self, template):
        """
        If `template` contains “{…}”, look up the current
        mapping_item’s metadata and do a .format(**meta), otherwise
        return it unchanged.
        """
        return self.runtime_manager.format_metadata(
            self.control["mapping"], self.container_position, template
        )

    def refresh_after_mapping_item_change(
        self, current_listitem, container_position, focus_id
    ):
        """
        If this control has a 'field', refresh its UI and reset its JSON
        value if no longer allowed, using the declared default when available.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that currently has focus.
        """
        self.current_listitem = current_listitem
        self.container_position = container_position

        if "field" not in self.control:
            return

        val = self._get_setting_value()
        allowed = self._allowed_items()
        if allowed and val not in allowed:
            if cfg_key := self._linked_config():
                cfg_data = self.runtime_manager.configs_data.get(cfg_key, {})
                default_val = cfg_data.get("default", allowed[0])
            else:
                default_val = allowed[0]

            self._set_setting_value(default_val)

        self.update_value(current_listitem, container_position)
        self.update_visibility(current_listitem, container_position, focus_id)

    def set_instance_labels(self, focused_control_id, instance=None):
        """
        Update the label and secondary label (label2) on a control instance.

        :param focused_control_id: GUI control ID that currently has focus.
        :param instance: The GUI control to update.
        """
        if instance is None:
            instance = self.instance
        link = self._get_active_link()
        current_value = self._get_setting_value()
        raw_label = link.get("label") or self.control.get("label", "")
        raw_label2 = (
            link.get("label2")
            or self.control.get("label2")
            or (current_value.capitalize() if current_value else "")
        )

        label, label2 = (
            self.runtime_manager.format_metadata(
                self.control["mapping"], self.container_position, txt
            )
            for txt in (raw_label, raw_label2)
        )

        colors = {
            param_name: resolve_colour(self.control[color_key])
            for color_key, param_name in COLOR_KEYS.items()
            if self.control.get(color_key)
        }

        if focused_control_id != instance.getId() and (c := colors.get("textColor")):
            label2 = f"[COLOR {c}]{label2}[/COLOR]"

        instance.setLabel(label=label or "", label2=label2 or "", **colors)

    def update_visibility(
        self, current_listitem, container_position, focused_control_id
    ):
        """
        Evaluates and sets visibility based on the control's visible condition.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.

        """
        self.current_listitem = current_listitem
        self.container_position = container_position

        link = self._get_active_link()
        visible_condition = (
            link.get("visible", "") if link else self.control.get("visible", "")
        )

        is_visible = (
            self.rule_engine.evaluate(visible_condition, runtime=True)
            if visible_condition
            else True
        )

        self.instance.setVisible(is_visible)

    def request_focus_change(self, target_id):
        self.focus_target_id = target_id


class ButtonHandler(BaseControlHandler):
    """
    Routes control onclick configs to the appropriate OnClickActions method.
    """

    ACTIONS = {
        "select": OnClickActions.select,
        "browse": OnClickActions.browse,
        "browse_single": OnClickActions.browse_single,
        "browse_multiple": OnClickActions.browse_multiple,
        "custom": OnClickActions.custom,
    }

    def handle_interaction(
        self, current_listitem, container_position, focused_control_id, a_id
    ):
        """
        Dispatches the onclick action when the button is activated.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Index in the runtime list.
        :param focused_control_id: ID of the focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.container_position = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or not self._get_active_link()
        ):
            return

        onclick = self.control.get("onclick")
        if not onclick:
            return

        action_type = onclick.get("type", "custom").lower()
        action_type = {
            "browsesingle": "browse_single",
            "browsemultiple": "browse_multiple",
        }.get(action_type, action_type)

        handler = self.ACTIONS.get(action_type, OnClickActions.custom)
        cfg = self._build_cfg(onclick)
        result = handler(cfg)
        if isinstance(result, int):
            if result < 0:
                return
            items = cfg["items"]
            if 0 <= result < len(items):
                result = items[result]
        if result is not None:
            self._set_setting_value(result)
            if "field" not in self.control:
                self.parent.onMappingItemChanged()

    def _build_cfg(self, onclick):
        """
        Build the flat config dict for OnClickActions, merging core and optional keys.
        """
        optional = (
            "browseType",
            "shares",
            "mask",
            "useThumbs",
            "treatAsFolder",
            "default",
            "enableMultiple",
            "autoclose",
            "preselect",
            "useDetails",
        )
        return {
            "heading": onclick.get("heading", ""),
            "action": onclick.get("action"),
            "items": onclick.get("items") or self._allowed_items(),
            **{k: onclick[k] for k in optional if k in onclick},
        }

    def update_value(self, current_listitem, container_position):
        """
        No-op stub to avoid breaking handler.update_value loop through all
        controls in window class.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        self.current_listitem = current_listitem
        self.container_position = container_position

    def update_visibility(
        self, current_listitem, container_position, focused_control_id
    ):
        """
        Sets visibility and label/label2 for the radiobutton control.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.
        """
        super().update_visibility(
            current_listitem, container_position, focused_control_id
        )
        self.set_instance_labels(focused_control_id)


class RadioButtonHandler(BaseControlHandler):
    """
    Handles interactions and updates for radiobutton controls.
    """

    def handle_interaction(
        self, current_listitem, container_position, focused_control_id, a_id
    ):
        """
        Toggles the boolean setting if user selects the radiobutton.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.container_position = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or not self._get_active_link()
        ):
            return

        new_value = "true" if self.instance.isSelected() else "false"
        self._set_setting_value(new_value)

    def update_value(self, current_listitem, container_position):
        """
        Updates the selected state and enabled status of the radio control.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        self.current_listitem = current_listitem
        self.container_position = container_position

        allowed = self._allowed_items()
        current = self._get_setting_value()
        self.instance.setSelected(current == "true")
        self.instance.setEnabled(len(allowed) > 1)

    def update_visibility(
        self, current_listitem, container_position, focused_control_id
    ):
        """
        Sets visibility and label/label2 for the radiobutton control.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.
        """
        super().update_visibility(
            current_listitem, container_position, focused_control_id
        )
        self.set_instance_labels(focused_control_id)


class SliderHandler(BaseControlHandler):
    """
    Handles slider controls mapped to a multi-option config.
    """

    def handle_interaction(
        self, current_listitem, container_position, focused_control_id, a_id
    ):
        """
        Updates the skin string when the user interacts with the slider.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT

        self.current_listitem = current_listitem
        self.container_position = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id
            not in (
                ACTION_MOVE_LEFT,
                ACTION_MOVE_RIGHT,
            )
            or not self._get_active_link()
        ):
            return

        values = self._allowed_items()
        idx = self.instance.getInt()
        if 0 <= idx < len(values):
            self._set_setting_value(values[idx])

    def update_value(self, current_listitem, container_position):
        """
        Updates the slider to reflect the current config value.

        :param current_listitem: Currently focused static control ID.
        :param container_position: Current index position in the runtime list.
        :return: True if more than one values are available, otherwise False.
        """
        self.current_listitem = current_listitem
        self.container_position = container_position

        if not self._linked_config():
            return False

        values = self._allowed_items()
        current = self._get_setting_value()
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        self.instance.setInt(idx, 0, 1, max(len(values) - 1, 0))
        enabled = len(values) > 1
        self.instance.setEnabled(enabled)
        return enabled


class SliderExHandler(SliderHandler):
    """
    Composite slider + button control.  Select left/right on the slider,
    or press select to flip focus between slider and its label-button.
    """

    def __init__(self, control, slider_instance, button_instance, runtime_manager):
        """
        :param control: Control definition.
        :param slider_instance: Main slider control instance.
        :param button_instance: Associated label button control.
        """
        super().__init__(control, slider_instance, runtime_manager)
        self.button_instance = button_instance
        self.button_id = button_instance.getId()

    def handle_interaction(
        self, current_listitem, container_position, focused_control_id, a_id
    ):
        """
        Handles focus toggle or delegates to slider handler based on action.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.container_position = container_position

        if a_id == ACTION_SELECT_ITEM:
            if self._on_button_focused(focused_control_id):
                self.request_focus_change(self.instance.getId())
            elif self._on_slider_focused(focused_control_id):
                self.request_focus_change(self.button_instance.getId())
        else:
            super().handle_interaction(
                current_listitem,
                container_position,
                focused_control_id,
                a_id,
            )

    def update_value(self, current_listitem, container_position):
        """
        Passes slider update from parent class then enables/disables button accordingly.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        enabled = super().update_value(current_listitem, container_position)
        self.button_instance.setEnabled(enabled)

    def update_visibility(
        self, current_listitem, container_position, focused_control_id
    ):
        """
        Updates slider visibility and updates the button's label/label2.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.
        """
        self.current_listitem = current_listitem
        self.container_position = container_position

        super().update_visibility(
            current_listitem, container_position, focused_control_id
        )
        self.set_instance_labels(
            focused_control_id,
            instance=self.button_instance,
        )

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
