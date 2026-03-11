# author: realcopacetic

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, skin_string
from resources.lib.windows.onclick_actions import OnClickActions

if TYPE_CHECKING:
    from resources.lib.builders.runtime import RuntimeStateManager

COLOR_KEYS = {
    "textcolor": "textColor",
    "focusedcolor": "focusedColor",
    "disabledcolor": "disabledColor",
    "shadowcolor": "shadowColor",
}


def resolve_color(value: str) -> str:
    """
    Parse a colour value from a hex string or ``$INFO[]`` reference.

    :param value: Raw colour string (hex or ``$INFO[...]`` expression).
    :return: Colour in ``0xRRGGBBAA`` format.
    """
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

    _updates_labels = True

    def __init__(
        self, control: dict, instance: object, runtime_manager: RuntimeStateManager
    ) -> None:
        """
        Initialise the handler with its control definition, GUI instance,
        and runtime state manager reference.

        :param control: Dictionary defining control from JSON.
        :param instance: Kodi GUI control instance. Type depends on control type.
        :param runtime_manager: Runtime state manager for reading/writing values.
        """
        self.control = control
        self.instance = instance
        self.runtime_manager = runtime_manager
        self.rule_engine = RuleEngine()

        self.mapping_key = control["mapping"]
        self.description = control.get("description")
        self.field = control.get("field")
        self.placeholders = runtime_manager.mappings.get(self.mapping_key, {}).get(
            "placeholders", {}
        )
        self._link_data_cache = None
        self.is_dynamic_linked = control.get("mode") == "dynamic" and self.field
        self.config_field_template = (
            runtime_manager.mappings[self.mapping_key]
            .get("config_fields", {})
            .get(self.field)
            if self.is_dynamic_linked
            else None
        )
        self.current_listitem = None
        self.source_index = None
        self.focus_target_id = None

    @property
    def focus_ids(self) -> set[int]:
        """
        Control IDs that this handler responds to.

        :return: Set of Kodi control IDs.
        """
        return {self.instance.getId()}

    def _get_active_link(self) -> dict:
        """
        Return the cached contextual binding for the current listitem,
        resolving it on first access.

        :return: Matching binding dictionary, or empty dict.
        """
        if self._link_data_cache is None:
            self._link_data_cache = self._resolve_active_link()
        return self._link_data_cache

    def _resolve_active_link(self) -> dict:
        """
        Resolve the active binding for the current listitem. For dynamic-linked
        controls, builds the linked_config key from the current mapping_item.
        For static controls, matches by update_trigger.

        :return: Matching dynamic_link dictionary, or empty dict if no match.
        """
        if self.is_dynamic_linked and self.config_field_template:
            try:
                current = self.runtime_manager.get_runtime_setting(
                    self.mapping_key, self.source_index, "mapping_item"
                )
                sub_map = {ph: current for ph in self.placeholders.values()}
                sub_map["index"] = self.source_index
                return {"linked_config": self.config_field_template.format(**sub_map)}
            except Exception as e:
                log.debug(f"Failed to resolve dynamic link: {e}")

        trigger = f"focused({self.current_listitem})"
        try:
            return next(
                (
                    link
                    for link in self.control.get("contextual_bindings", [])
                    if link.get("update_trigger") == trigger
                ),
                {},
            )
        except Exception as e:
            log.debug(f"Fallback contextual_bindings failed: {e}")
            return {}

    def _linked_config(self) -> str | None:
        """
        Return the linked_config ID for the currently matched dynamic link.

        :return: config ID string or None.
        """
        return self._get_active_link().get("linked_config")

    def _allowed_items(self) -> list[str]:
        """
        Return the list of values this control may choose from:

        :return: List of approved string values.
        """
        cfg = self._linked_config()
        return (
            self.runtime_manager.configs_data.get(cfg, {}).get("items", [])
            if cfg
            else (
                []
                if self.field and not self.config_field_template
                else self.runtime_manager.mappings.get(self.control["mapping"], {}).get(
                    "items", []
                )
            )
        )

    def config_context(self) -> tuple[str | None, dict]:
        """
        Resolve the linked config and its data for the current control.

        :return: Tuple of ``(cfg, cfg_data)`` where cfg_data may be None.
        """
        cfg = self._linked_config()
        cfg_data = self.runtime_manager.configs_data.get(cfg, {}) if cfg else None
        return cfg, cfg_data

    def _get_setting_value(self) -> str | None:
        """
        Return the current value for this control at the given list index.
        First checks for linked_config then falls back to mapping items.

        :return: The current setting or mapping_item value, or None.
        """
        if self.source_index is None or self.source_index < 0:
            return None

        link = self._get_active_link()
        if cfg := link.get("linked_config"):
            cfg_data = self.runtime_manager.configs_data.get(cfg, {})
            mode = cfg_data.get("mode", "static")
            default = cfg_data.get("default", "")

            if mode == "dynamic" and self.is_dynamic_linked:
                try:
                    return self.runtime_manager.get_runtime_setting(
                        self.mapping_key, self.source_index, self.field
                    )
                except (IndexError, KeyError):
                    return default

            return infolabel(f"Skin.String({cfg})").strip()

        try:
            return self.runtime_manager.get_runtime_setting(
                self.mapping_key, self.source_index, self.field or "mapping_item"
            )
        except (IndexError, KeyError):
            if self.field and not self.config_field_template:
                return None

            default_order = self.runtime_manager.mappings.get(self.mapping_key, {}).get(
                "default_order", []
            )
            if 0 <= self.source_index < len(default_order):
                return default_order[self.source_index]
            return None

    def _set_setting_value(self, value: str) -> None:
        """
        Set a new value for this control at the given list index.
        Notifies the parent editor if a skin string was changed,
        so it knows to rebuild on close.

        :param value: The new value to store.
        """
        if self._get_setting_value() == value:
            return

        cfg, cfg_data = self.config_context()
        if cfg_data:
            mode = cfg_data.get("mode", "static")
            if mode == "dynamic" and self.is_dynamic_linked:
                try:
                    self.runtime_manager.update_runtime_setting(
                        self.mapping_key, self.source_index, self.field, value
                    )
                except IndexError:
                    pass
            else:
                skin_string(cfg, value)
                if hasattr(self, "parent"):
                    self.parent.skin_strings_changed = True
            return

        try:
            self.runtime_manager.update_runtime_setting(
                self.mapping_key,
                self.source_index,
                self.field or "mapping_item",
                value,
            )
        except IndexError:
            pass

    def _apply_metadata(self, template: str) -> str:
        """
        If 'template' contains '{…}', look up the current
        mapping_item's metadata and do a .format(**meta), otherwise
        return it unchanged.
        """
        return self.runtime_manager.format_metadata(
            self.control["mapping"], self.source_index, template
        )

    def _resolve_label(self, raw: str) -> str:
        """
        Substitute metadata placeholders and resolve Kodi tokens.

        :param raw: Template string with {metadata} and/or $LOCALIZE tokens.
        :return: Resolved display string.
        """
        formatted = self.runtime_manager.format_metadata(
            self.control["mapping"], self.source_index, raw
        )
        return infolabel(formatted) if formatted.startswith("$") else formatted

    def set_instance_labels(
        self, focused_control_id: int, instance: object | None = None
    ) -> None:
        """
        Update the label and secondary label (label2) on a control instance.

        :param focused_control_id: GUI control ID that currently has focus.
        :param instance: The GUI control to update.
        """
        if instance is None:
            instance = self.instance
        link = self._get_active_link()
        current_value = self._get_setting_value()
        if self.field:
            try:
                preset_key = self.runtime_manager.get_runtime_setting(
                    self.mapping_key, self.source_index, "mapping_item"
                )
            except (IndexError, KeyError):
                preset_key = current_value
        else:
            preset_key = current_value
        meta = (
            self.runtime_manager.mappings[self.mapping_key]
            .get("metadata", {})
            .get(preset_key, {})
        )
        raw_label = link.get("label") or self.control.get("label", "")
        cfg_key = self._linked_config()
        cfg_labels = (
            self.runtime_manager.configs_data.get(cfg_key, {}).get("labels", {})
            if cfg_key
            else {}
        )
        if "label2" in self.control and self.control["label2"] is not None:
            raw_label2 = self.control["label2"]
        elif "label2" in link:
            raw_label2 = link["label2"]
        else:
            user_val = current_value if self.field else None
            meta_label = meta.get(self.field or "label")
            raw_label2 = (
                cfg_labels.get(current_value)
                or user_val
                or meta_label
                or current_value
                or ""
            )

        label, label2 = (self._resolve_label(txt) for txt in (raw_label, raw_label2))

        colors = {
            param_name: resolve_color(self.control[color_key])
            for color_key, param_name in COLOR_KEYS.items()
            if self.control.get(color_key)
        }

        if focused_control_id != instance.getId() and (c := colors.get("textColor")):
            label2 = f"[COLOR {c}]{label2}[/COLOR]"

        instance.setLabel(
            label=label if label else " ", label2=label2 if label2 else " ", **colors
        )

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Syncs handler state with the current listitem and position, clearing
        the link data cache so it will be re-resolved on next access.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        self.current_listitem = current_listitem
        self.source_index = container_position
        self._link_data_cache = None

    def update_visibility(
        self, current_listitem: str, container_position: int, focused_control_id: int
    ) -> None:
        """
        Evaluates and sets visibility based on the control's visible condition.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.
        """
        # Re-assign in case update_visibility is called independently of update_value
        self.current_listitem = current_listitem
        self.source_index = container_position

        link = self._get_active_link()
        raw_condition = link.get("visible") or self.control.get("visible", "")
        visible_condition = self.runtime_manager.format_metadata(
            self.control["mapping"], self.source_index, raw_condition
        )
        is_visible = (
            self.rule_engine.evaluate(visible_condition, runtime=True)
            if visible_condition
            else True
        )

        self.instance.setVisible(is_visible)
        if self._updates_labels:
            self.set_instance_labels(focused_control_id)

    def refresh_after_mapping_item_change(
        self, current_listitem: str, container_position: int, focus_id: int
    ) -> None:
        """
        If this control has a 'field', refresh its UI and reset its JSON
        value if no longer allowed, using the declared default when available.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focus_id: GUI control ID that currently has focus.
        """
        self.current_listitem = current_listitem
        self.source_index = container_position
        self._link_data_cache = None

        if not self.field:
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

    def request_focus_change(self, target_id: int) -> None:
        """
        Request that the editor change focus to a different control.

        :param target_id: Kodi control ID to receive focus.
        """
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
        "browse_content": OnClickActions.browse_content,
        "colorpicker": OnClickActions.colorpicker,
        "input": OnClickActions.input,
        "numeric": OnClickActions.numeric,
        "custom": OnClickActions.custom,
    }

    def _build_cfg(self, onclick: dict) -> dict:
        """
        Build the flat config dict for OnClickActions, merging core
        and optional keys with resolved items and display labels.

        :param onclick: Raw onclick definition from the control JSON.
        :return: Merged config dict ready for an OnClickActions method.
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
            "mode",
            "sibling_fields",
            "result_field",
        )

        # Fetch items, then resolve display labels from config labels, metadata, or title-case
        items = onclick.get("items") or self._allowed_items()
        cfg_key = self._linked_config()
        cfg_labels = (
            self.runtime_manager.configs_data.get(cfg_key, {}).get("labels", {})
            if cfg_key
            else {}
        )
        display_items = [
            infolabel(lbl) if isinstance(lbl, str) and lbl.startswith("$") else lbl
            for item in items
            for lbl in [
                (
                    cfg_labels.get(item)
                    or self.runtime_manager.mappings[self.mapping_key]
                    .get("metadata", {})
                    .get(item, {})
                    .get("label")
                    or item.replace("_", " ").title()
                )
            ]
        ]
        current_value = self._get_setting_value()
        try:
            preselect = items.index(current_value)
        except ValueError:
            preselect = 0

        return {
            "heading": onclick.get("heading", ""),
            "action": self._apply_metadata(onclick.get("action", "")),
            "items": items,
            "display_items": display_items,
            "preselect": preselect,
            **{k: onclick[k] for k in optional if k in onclick},
        }

    def run_preflight_dialog(self) -> tuple[object, dict] | None:
        """
        Run this handler's onclick dialog without applying the result.

        :return: Tuple of ``(result, cfg)`` or None if no onclick defined.
        """
        onclick = self.control.get("onclick")
        if not onclick:
            return None

        cfg = self._build_cfg(onclick)
        action_type = onclick.get("type", "custom").lower()
        action_type = {
            "browsesingle": "browse_single",
            "browsemultiple": "browse_multiple",
        }.get(action_type, action_type)

        result = self.ACTIONS.get(action_type, OnClickActions.custom)(cfg)
        return result, cfg

    def apply_result(self, result: object, cfg: dict) -> object:
        """
        Write a dialog result to runtime state — siblings and main value.
        Separated from handle_interaction so ``_on_add`` can apply
        pre-flight results to a newly inserted entry.

        :param result: Raw dialog return value.
        :param cfg: Config dict from ``_build_cfg``.
        :return: The resolved value that was written, or None.
        """
        if isinstance(result, dict) and "path" in result:
            for result_key, control_name in cfg.get("sibling_fields", {}).items():
                if result_key not in result:
                    continue

                sibling_cfg = self.parent.dynamic_controls.get(control_name, {})
                runtime_field = sibling_cfg.get("field", control_name)
                try:
                    self.runtime_manager.update_runtime_setting(
                        self.mapping_key,
                        self.source_index,
                        runtime_field,
                        result[result_key],
                    )
                except IndexError:
                    pass

            result = result.get(cfg.get("result_field", "path"), result["path"])

        if result is not None:
            self._set_setting_value(result)

        return result

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Dispatches the onclick action when the button is activated.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Index in the runtime list.
        :param focused_control_id: ID of the focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.source_index = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or (self.config_field_template and not self._get_active_link())
        ):
            return

        preflight = self.run_preflight_dialog()
        if preflight is None:
            return

        result, cfg = preflight
        if isinstance(result, int):
            if result < 0:
                return      
            items = cfg["items"]
            if 0 <= result < len(items):
                result = items[result]

        if result is not None:
            self.apply_result(result, cfg)
            if self.control.get("role") == "item_picker":
                self.parent._seed_metadata()
                self.parent._build_dicts()
                self.parent._refresh_handlers_after_mapping_change()
            else:
                self.parent._build_dicts()
                self.parent._refresh_ui()


class CycleHandler(BaseControlHandler):
    """
    A button that cycles through allowed values on select.
    Displays the current value as label2. Each press advances
    to the next item in the list, wrapping around at the end.
    """

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Advances to the next allowed value on select.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.source_index = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or not self._get_active_link()
        ):
            return

        values = self._allowed_items()
        if not values:
            return

        current = self._get_setting_value()
        try:
            idx = values.index(current)
        except ValueError:
            idx = -1

        next_idx = (idx + 1) % len(values)
        self._set_setting_value(values[next_idx])
        self.parent._refresh_ui()

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Updates enabled state based on whether there are multiple values to cycle.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        super().update_value(current_listitem, container_position)
        self.instance.setEnabled(len(self._allowed_items()) > 1)


class EditHandler(BaseControlHandler):
    """
    Handles inline edit controls. The label field is used as hint text and keyboard
    heading via setLabel(). Saves on keyboard close or when the user navigates away.
    """

    def __init__(
        self, control: dict, instance: object, runtime_manager: RuntimeStateManager
    ) -> None:
        super().__init__(control, instance, runtime_manager)
        self._cached_text = ""

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Reads the edit control's text after the keyboard closes and persists it.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Index in the runtime list.
        :param focused_control_id: ID of the focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import (
            ACTION_MOVE_DOWN,
            ACTION_MOVE_LEFT,
            ACTION_MOVE_RIGHT,
            ACTION_MOVE_UP,
            ACTION_NAV_BACK,
            ACTION_SELECT_ITEM,
        )

        SAVE_ACTIONS = (
            ACTION_SELECT_ITEM,
            ACTION_MOVE_UP,
            ACTION_MOVE_DOWN,
            ACTION_MOVE_LEFT,
            ACTION_MOVE_RIGHT,
            ACTION_NAV_BACK,
        )

        self.current_listitem = current_listitem
        self.source_index = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id not in SAVE_ACTIONS
            or (self.config_field_template and not self._get_active_link())
        ):
            return

        value = self.instance.getText().strip()
        if not value or value == self._cached_text:
            return

        self._cached_text = value
        self._set_setting_value(value)
        self.parent._build_dicts()
        self.parent._refresh_list_row(self.parent.container_position)

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Updates the edit control to reflect the current stored value.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        super().update_value(current_listitem, container_position)
        current = self._get_setting_value()
        display = self._resolve_label(current) if current else ""
        self._cached_text = display
        self.instance.setText(display)


class RadioButtonHandler(BaseControlHandler):
    """
    Handles interactions and updates for radiobutton controls.
    """

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Toggles the boolean setting if user selects the radiobutton.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.source_index = container_position

        if (
            focused_control_id != self.instance.getId()
            or a_id != ACTION_SELECT_ITEM
            or not self._get_active_link()
        ):
            return

        values = self._allowed_items()
        if len(values) < 2:
            return

        new_value = values[0] if self.instance.isSelected() else values[1]
        self._set_setting_value(new_value)

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Updates the selected state and enabled status of the radio control.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        super().update_value(current_listitem, container_position)
        allowed = self._allowed_items()
        current = self._get_setting_value()
        first = allowed[0] if allowed else "true"
        self.instance.setSelected(current == first)
        self.instance.setEnabled(len(allowed) > 1)


class SliderHandler(BaseControlHandler):
    """
    Handles slider controls mapped to a multi-option config.
    """

    _updates_labels = False

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Updates the skin string when the user interacts with the slider.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT

        self.current_listitem = current_listitem
        self.source_index = container_position

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

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Updates the slider to reflect the current config value.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        super().update_value(current_listitem, container_position)

        if not self._linked_config():
            return

        values = self._allowed_items()
        current = self._get_setting_value()
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        self.instance.setInt(idx, 0, 1, max(len(values) - 1, 0))
        enabled = len(values) > 1
        self.instance.setEnabled(enabled)
        self._enabled = enabled


class SliderExHandler(SliderHandler):
    """
    Composite slider + button control.  Select left/right on the slider,
    or press select to flip focus between slider and its label-button.
    """

    def __init__(
        self,
        control: dict,
        slider_instance: object,
        button_instance: object,
        runtime_manager: RuntimeStateManager,
    ) -> None:
        """
        :param control: Control definition.
        :param slider_instance: Main slider control instance.
        :param button_instance: Associated label button control.
        """
        super().__init__(control, slider_instance, runtime_manager)
        self.button_instance = button_instance
        self.button_id = button_instance.getId()

    @property
    def focus_ids(self) -> set[int]:
        """
        Control IDs for both the slider and its companion button.

        :return: Set containing slider and button control IDs.
        """
        return {self.instance.getId(), self.button_id}

    def handle_interaction(
        self,
        current_listitem: str,
        container_position: int,
        focused_control_id: int,
        a_id: int,
    ) -> None:
        """
        Handles focus toggle or delegates to slider handler based on action.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        self.current_listitem = current_listitem
        self.source_index = container_position

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

    def update_value(self, current_listitem: str, container_position: int) -> None:
        """
        Passes slider update from parent class then enables/disables button accordingly.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        """
        super().update_value(current_listitem, container_position)
        self.button_instance.setEnabled(self._enabled)

    def update_visibility(
        self, current_listitem: str, container_position: int, focused_control_id: int
    ) -> None:
        """
        Updates slider visibility and updates the button's label/label2.

        :param current_listitem: Named ID of the currently selected listitem.
        :param container_position: Current index position in the runtime list.
        :param focused_control_id: GUI control ID that has current focus.
        """
        super().update_visibility(
            current_listitem, container_position, focused_control_id
        )
        self.set_instance_labels(
            focused_control_id,
            instance=self.button_instance,
        )

    def _on_button_focused(self, focused_id: int) -> bool:
        """
        Check whether the companion button has focus.

        :param focused_id: Currently focused control ID.
        :return: True if the button is focused.
        """
        return self.button_instance.getId() == focused_id

    def _on_slider_focused(self, focused_id: int) -> bool:
        """
        Check whether the slider has focus.

        :param focused_id: Currently focused control ID.
        :return: True if the slider is focused.
        """
        return self.instance.getId() == focused_id
