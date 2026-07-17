# author: realcopacetic

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from xbmcgui import (
    ACTION_MOVE_DOWN,
    ACTION_MOVE_LEFT,
    ACTION_MOVE_RIGHT,
    ACTION_MOVE_UP,
    ACTION_NAV_BACK,
    ACTION_SELECT_ITEM,
)

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel
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
    ACCEPTED_ACTIONS: tuple = (ACTION_SELECT_ITEM,)
    _needs_link = False

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
        mapping_def = runtime_manager.mappings.get(self.mapping_key, {})
        self.placeholders = mapping_def.get("placeholders", {})
        self._link_data_cache = None
        self._link_cache_key = None
        # Storage semantics come from the session mapping, not the control:
        # controls carry no mode of their own.
        self.is_dynamic_linked = mapping_def.get("mode") == "dynamic" and bool(
            self.field
        )
        self.focus_target_id = None
        self.parent = None  # set by DynamicEditor.onInit

    @property
    def config_field_template(self) -> str | None:
        """Template governing this control's field for the focused entry."""
        if not self.is_dynamic_linked:
            return None
        try:
            item = self.runtime_manager.get_runtime_setting(
                self.mapping_key, self.source_index, "mapping_item"
            )
        except (IndexError, KeyError):
            item = None
        return self.runtime_manager.field_template(self.mapping_key, item, self.field)

    @property
    def current_listitem(self) -> str | None:
        """Selected listitem id, read from the parent editor."""
        return self.parent.current_listitem if self.parent else None

    @property
    def source_index(self) -> int:
        """Source index of the selected entry, read from the parent editor."""
        return self.parent._source_index if self.parent else -1

    @property
    def focus_ids(self) -> set[int]:
        """
        Control IDs that this handler responds to.

        :return: Set of Kodi control IDs.
        """
        return {self.instance.getId()}

    def _active_link(self) -> dict:
        """
        Binding for the focused listitem, cached per (selection, state
        version) so it self-invalidates on focus change or state write.

        :return: Matching binding dictionary, or empty dict.
        """
        key = (self.current_listitem, self.runtime_manager.state_version)
        if self._link_cache_key == key and self._link_data_cache is not None:
            return self._link_data_cache
        self._link_cache_key = key

        if self.is_dynamic_linked and self.config_field_template:
            sub_map = self.runtime_manager.entry_substitutions(
                self.mapping_key, self.source_index
            )
            if sub_map:
                try:
                    cfg_key = self.config_field_template.format(**sub_map)
                    cfg_data = self.runtime_manager.configs.resolve(
                        self.mapping_key, self.config_field_template, sub_map
                    )
                except KeyError as e:
                    log.debug(f"Failed to resolve dynamic link: {e}")
                else:
                    self._link_data_cache = {
                        "linked_config": cfg_key,
                        "config": cfg_data,
                    }
                    return self._link_data_cache

        self._link_data_cache = {}
        return self._link_data_cache

    def _coerce_to_allowed(self) -> str | None:
        """
        Snap the stored value to the cfg default (or first allowed item if
        no default) when the current value isn't in the allowed list.

        :return: The valid value after coercion, or None if no items.
        """
        allowed = self._allowed_items()
        if not allowed:
            return None
        current = self._get_setting_value()
        if current in allowed:
            return current
        link = self._active_link()
        default_val = (
            link["config"].get("default", allowed[0])
            if link.get("linked_config")
            else allowed[0]
        )
        self._set_setting_value(default_val)
        return default_val

    def _allowed_items(self) -> list[str]:
        """
        Return the list of values this control may choose from.

        :return: List of approved string values.
        """
        link = self._active_link()
        cfg = link.get("linked_config")
        return (
            link["config"].get("items", [])
            if cfg
            else (
                []
                if self.field and not self.config_field_template
                else self.runtime_manager.mappings.get(self.control["mapping"], {}).get(
                    "items", []
                )
            )
        )

    def _get_setting_value(self) -> str | None:
        """
        Return the current value for this control at the given list index.
        Checks the linked config first, then the entry field directly.

        :return: The current setting or mapping_item value, or None.
        """
        if self.source_index is None or self.source_index < 0:
            return None

        link = self._active_link()
        if link.get("linked_config"):
            default = link["config"].get("default", "")
            try:
                return self.runtime_manager.get_runtime_setting(
                    self.mapping_key, self.source_index, self.field
                )
            except (IndexError, KeyError):
                return default

        try:
            return self.runtime_manager.get_runtime_setting(
                self.mapping_key, self.source_index, self.field or "mapping_item"
            )
        except (IndexError, KeyError):
            # Entries are universally seeded, so a miss means an invalid
            # index — don't mask it with a positional default_order guess.
            return None

    def _set_setting_value(self, value: str) -> None:
        """
        Set a new value for this control at the given list index.

        :param value: The new value to store.
        """
        if self._get_setting_value() == value:
            return

        link = self._active_link()
        if link.get("config"):
            self.runtime_manager.update_runtime_setting(
                self.mapping_key, self.source_index, self.field, value
            )
            return

        self.runtime_manager.update_runtime_setting(
            self.mapping_key,
            self.source_index,
            self.field or "mapping_item",
            value,
        )

    def _preset_key(self) -> str | None:
        """
        Mapping_item used for metadata lookup; falls back to current value
        when field has no runtime entry.

        :return: Mapping_item string or current value.
        """
        current = self._get_setting_value()
        if not self.field:
            return current
        try:
            return self.runtime_manager.get_runtime_setting(
                self.mapping_key, self.source_index, "mapping_item"
            )
        except (IndexError, KeyError):
            return current

    def _raw_labels(self) -> tuple[str, str]:
        """
        Resolve raw label and label2 strings before token substitution.

        :return: ``(raw_label, raw_label2)`` tuple.
        """
        link = self._active_link()
        current = self._get_setting_value()
        raw_label = link.get("label") or self.control.get("label", "")

        if self.control.get("label2") is not None:
            return raw_label, self.control["label2"]
        if "label2" in link:
            return raw_label, link["label2"]

        cfg_labels = link.get("config", {}).get("labels", {})
        meta = (
            self.runtime_manager.mappings[self.mapping_key]
            .get("metadata", {})
            .get(self._preset_key(), {})
        )
        raw_label2 = (
            cfg_labels.get(current)
            or (current if self.field else None)
            or meta.get(self.field or "label")
            or current
            or ""
        )
        return raw_label, raw_label2

    def set_instance_labels(
        self,
        focused_control_id: int,
        instance: object | None = None,
        label_color: str | None = None,
        label2_color: str | None = None,
    ) -> None:
        """
        Update the label and label2 on a control instance.

        :param focused_control_id: GUI control ID with current focus.
        :param instance: Target control instance; defaults to ``self.instance``.
        :param label_color: Optional colour wrap for label (palette name or hex), overriding focus styling.
        :param label2_color: Optional colour wrap for label2 (palette name or hex), overriding focus styling.
        """
        if instance is None:
            instance = self.instance

        raw_label, raw_label2 = self._raw_labels()
        label = self.runtime_manager.format_metadata(
            self.mapping_key, self.source_index, raw_label, localize=True
        )
        label2 = self.runtime_manager.format_metadata(
            self.mapping_key, self.source_index, raw_label2, localize=True
        )
        colors = {
            param: resolve_color(self.control[color_key])
            for color_key, param in COLOR_KEYS.items()
            if self.control.get(color_key)
        }

        if (
            label2_color is None
            and focused_control_id != instance.getId()
            and (c := colors.get("textColor"))
        ):
            label2 = f"[COLOR {c}]{label2}[/COLOR]"
        if label_color:
            label = f"[COLOR {label_color}]{label}[/COLOR]"
        if label2_color:
            label2 = f"[COLOR {label2_color}]{label2}[/COLOR]"

        instance.setLabel(label=label or " ", label2=label2 or " ", **colors)

    def update_value(self) -> None:
        """Hook: sync the control instance to the selected entry's value."""

    def update_visibility(self, focused_control_id: int) -> None:
        """
        Evaluates and sets visibility based on the control's visible condition.

        :param focused_control_id: GUI control ID that has current focus.
        """
        link = self._active_link()
        raw_condition = link.get("visible") or self.control.get("visible", "")
        visible_condition = self.runtime_manager.format_metadata(
            self.mapping_key, self.source_index, raw_condition
        )
        is_visible = (
            self.rule_engine.evaluate(visible_condition, runtime=True)
            if visible_condition
            else True
        )

        self.instance.setVisible(is_visible)
        if self._updates_labels:
            self.set_instance_labels(focused_control_id)

    def handle_interaction(self, focused_control_id: int, a_id: int) -> None:
        """
        Guarded dispatch: runs ``_on_interact`` when this control is the
        action's target, the action is accepted, and any required link resolves.

        :param focused_control_id: ID of the control the action applied to.
        :param a_id: Kodi action ID.
        """
        if (
            focused_control_id not in self.focus_ids
            or a_id not in self.ACCEPTED_ACTIONS
            or not self._link_ok()
        ):
            return
        self._on_interact(focused_control_id, a_id)

    def _link_ok(self) -> bool:
        """
        Whether the active link satisfies this control's requirements.

        :return: True when interaction may proceed.
        """
        if self._needs_link:
            return bool(self._active_link())
        return not self.config_field_template or bool(self._active_link())

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """Hook: perform the control's action. Overridden per control type."""

    def refresh_after_mapping_item_change(self, focus_id: int) -> None:
        """
        Refresh UI and snap the field to a valid value if filtering
        invalidated the current one.

        :param focus_id: GUI control ID that currently has focus.
        """
        if self.field:
            self._coerce_to_allowed()
        self.update_value()
        self.update_visibility(focus_id)

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
        "browse_image": OnClickActions.browse_image,
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
            "folder",
        )

        # Fetch items, then resolve display labels from config labels, metadata, or title-case
        items = onclick.get("items") or self._allowed_items()
        link = self._active_link()
        cfg_labels = link.get("config", {}).get("labels", {})

        raw_labels = [
            cfg_labels.get(item)
            or self.runtime_manager.mappings[self.mapping_key]
            .get("metadata", {})
            .get(item, {})
            .get("label")
            or item.replace("_", " ").title()
            for item in items
        ]
        display_items = [
            infolabel(lbl) if isinstance(lbl, str) and lbl.startswith("$") else lbl
            for lbl in raw_labels
        ]
        current_value = self._get_setting_value()
        try:
            preselect = items.index(current_value)
        except ValueError:
            preselect = 0

        return {
            "heading": onclick.get("heading", ""),
            "action": self.runtime_manager.format_metadata(
                self.mapping_key, self.source_index, onclick.get("action", "")
            ),
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
            "browseimage": "browse_image",
        }.get(action_type, action_type)

        result = self.ACTIONS.get(action_type, OnClickActions.custom)(cfg)
        return result, cfg

    def apply_result(self, result: object, cfg: dict) -> object | None:
        """
        Write a dialog result to runtime state — siblings and main value.
        Separated from handle_interaction so ``_on_add`` can apply
        pre-flight results to a newly inserted entry.

        :param result: Raw dialog return value.
        :param cfg: Config dict from ``_build_cfg``.
        :return: The resolved value that was written, or None.
        """
        if isinstance(result, dict) and "path" in result:
            sibling_updates = {}
            for result_key, control_name in cfg.get("sibling_fields", {}).items():
                if result_key not in result:
                    continue
                sibling_cfg = self.parent.dynamic_controls.get(control_name, {})
                runtime_field = sibling_cfg.get("field", control_name)
                sibling_updates[runtime_field] = result[result_key]

            if sibling_updates:
                self.runtime_manager.update_runtime_settings(
                    self.mapping_key, self.source_index, sibling_updates
                )

            result = result.get(cfg.get("result_field", "path"), result["path"])

        if result is not None:
            self._set_setting_value(result)

        return result

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Dispatches the onclick action when the button is activated.

        :param focused_control_id: ID of the focused control.
        :param a_id: Kodi action ID.
        """
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
            # Same-preset re-pick is a no-op — leave the entry untouched
            if self.control.get("role") == "item_picker":
                try:
                    current = self.runtime_manager.get_runtime_setting(
                        self.mapping_key, self.source_index, "mapping_item"
                    )
                    if current == result:
                        return
                except (IndexError, KeyError):
                    pass

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

    _needs_link = True

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Advances to the next allowed value on select.

        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
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

    def update_value(self) -> None:
        """Snap to an allowed value, then update enabled state."""
        super().update_value()
        self._coerce_to_allowed()
        self.instance.setEnabled(len(self._allowed_items()) > 1)


class EditHandler(BaseControlHandler):
    """
    Handles inline edit controls. The label field is used as hint text and keyboard
    heading via setLabel(). Saves on keyboard close or when the user navigates away.
    """

    ACCEPTED_ACTIONS = (
        ACTION_SELECT_ITEM,
        ACTION_MOVE_UP,
        ACTION_MOVE_DOWN,
        ACTION_MOVE_LEFT,
        ACTION_MOVE_RIGHT,
        ACTION_NAV_BACK,
    )

    def __init__(
        self, control: dict, instance: object, runtime_manager: RuntimeStateManager
    ) -> None:
        """
        Initialise the edit handler with a cached-text guard for save dedup.

        :param control: Control definition.
        :param instance: Kodi edit control instance.
        :param runtime_manager: Runtime state manager.
        """
        super().__init__(control, instance, runtime_manager)
        self._cached_text = ""

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Reads the edit control's text after the keyboard closes and persists it.

        :param focused_control_id: ID of the focused control.
        :param a_id: Kodi action ID.
        """
        value = self.instance.getText().strip()
        if value == self._cached_text:
            return

        self._cached_text = value
        self._set_setting_value(value)
        self.parent._build_dicts()
        self.parent._refresh_list_row(self.parent.container_position)

    def update_value(self) -> None:
        """Updates the edit control to reflect the current stored value."""
        super().update_value()
        current = self._get_setting_value()
        display = (
            self.runtime_manager.format_metadata(
                self.mapping_key, self.source_index, current, localize=True
            )
            if current
            else ""
        )
        self._cached_text = display
        self.instance.setText(display)


class RadioButtonHandler(BaseControlHandler):
    """
    Handles interactions and updates for radiobutton controls.
    """

    _needs_link = True

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Toggles the boolean setting if user selects the radiobutton.

        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        values = self._allowed_items()
        if len(values) < 2:
            return

        new_value = values[0] if self.instance.isSelected() else values[1]
        self._set_setting_value(new_value)
        self.parent._refresh_ui()

    def update_value(self) -> None:
        """Updates the selected state and enabled status of the radio control."""
        super().update_value()
        allowed = self._allowed_items()
        current = self._coerce_to_allowed()
        first = allowed[0] if allowed else "true"
        self.instance.setSelected(current == first)
        self.instance.setEnabled(len(allowed) > 1)


class SliderHandler(BaseControlHandler):
    """
    Handles slider controls mapped to a multi-option config.
    """

    _updates_labels = False
    ACCEPTED_ACTIONS = (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT)
    _needs_link = True

    def __init__(
        self, control: dict, instance: object, runtime_manager: RuntimeStateManager
    ) -> None:
        """
        Initialise the slider handler with a default-disabled enable flag.

        :param control: Control definition.
        :param instance: Kodi slider control instance.
        :param runtime_manager: Runtime state manager.
        """
        super().__init__(control, instance, runtime_manager)
        self._enabled = False

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Updates the stored value when the user interacts with the slider.

        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        values = self._allowed_items()
        idx = self.instance.getInt()
        if 0 <= idx < len(values):
            self._set_setting_value(values[idx])
            self.parent._refresh_ui()

    def update_value(self) -> None:
        """Snap to an allowed value, then update slider index and enabled state."""
        super().update_value()

        if not self._active_link().get("linked_config"):
            return

        current = self._coerce_to_allowed()
        values = self._allowed_items()
        idx = values.index(current) if current in values else 0
        self.instance.setInt(idx, 0, 1, max(len(values) - 1, 0))
        enabled = len(values) > 1
        self.instance.setEnabled(enabled)
        self._enabled = enabled


class SliderExHandler(SliderHandler):
    """
    Composite slider + button control.  Select left/right on the slider,
    or press select to flip focus between slider and its label-button.
    """

    ACCEPTED_ACTIONS = (ACTION_SELECT_ITEM, ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT)

    def __init__(
        self,
        control: dict,
        slider_instance: object,
        button_instance: object,
        runtime_manager: RuntimeStateManager,
    ) -> None:
        """
        Wire up the slider and its companion label-button.

        :param control: Control definition.
        :param slider_instance: Main slider control instance.
        :param button_instance: Associated label button control.
        :param runtime_manager: Runtime state manager.
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

    def _on_interact(self, focused_control_id: int, a_id: int) -> None:
        """
        Handles focus toggle or delegates to slider handler based on action.

        :param focused_control_id: ID of currently focused control.
        :param a_id: Kodi action ID.
        """
        if a_id == ACTION_SELECT_ITEM:
            if focused_control_id == self.button_id:
                self.request_focus_change(self.instance.getId())
            else:
                self.request_focus_change(self.button_instance.getId())
            return
        if focused_control_id == self.instance.getId():
            super()._on_interact(focused_control_id, a_id)

    def update_value(self) -> None:
        """Passes slider update from parent class then enables/disables button accordingly."""
        super().update_value()
        self.button_instance.setEnabled(self._enabled)

    def update_visibility(self, focused_control_id: int) -> None:
        """
        Updates slider visibility and updates the button's label/label2.

        :param focused_control_id: GUI control ID that has current focus.
        """
        super().update_visibility(focused_control_id)
        slider_focused = focused_control_id == self.instance.getId()
        colors = self.parent._colors if self.parent else {}
        self.set_instance_labels(
            focused_control_id,
            instance=self.button_instance,
            label_color=colors.get("focused") if slider_focused else None,
            label2_color=(
                colors.get("focused") if slider_focused else colors.get("unfocused")
            ),
        )
