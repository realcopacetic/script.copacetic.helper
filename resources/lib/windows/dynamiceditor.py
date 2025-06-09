# author: realcopacetic

from pathlib import Path

import xbmcgui

from resources.lib.builders.builder_config import BUILDER_MAPPINGS
from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import (
    CONFIGS,
    CONTROLS,
    RUNTIME_STATE,
    SKINEXTRAS,
    execute,
    infolabel,
    log,
)
from resources.lib.windows.control_factory import DynamicControlFactory


class DynamicEditor(xbmcgui.WindowXMLDialog):
    """
    A dynamic skin settings editor window that adapts controls based on focus.
    Dynamically builds and manages visibility, interaction, and values for skin settings.
    """

    def __init__(self, xmlFilename, skinPath, defaultSkin, defaultRes):
        """
        Initialize the editor and prepare handlers for dynamic/static controls.

        :param xmlFilename: Name of the active XML window file.
        :param skinPath: Path to the current skin directory.
        :param defaultSkin: Name of the default skin.
        :param defaultRes: Default resolution.
        """
        super().__init__()
        self._xml_filename = xmlFilename.lower()
        self.controls_handler = JSONHandler(CONTROLS)

        self.mapping_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=["custom_mappings"],
            grouping_key=None,
        )
        self.all_mappings = {
            **BUILDER_MAPPINGS,
            **dict(self.mapping_merger.cached_merged_data),
        }
        self.runtime_manager = RuntimeStateManager(
            mappings=self.all_mappings,
            configs_path=CONFIGS,
            runtime_state_path=RUNTIME_STATE,
        )

        self.handlers = {}
        self.control_instances = {}
        self.current_listitem = None
        self.container_position = -1

        self.build_dicts()

    def build_dicts(self):
        """
        Populate control and skinsetting mappings from JSON definitions.
        Separates static and dynamic controls.
        """
        filtered_controls = {
            control_id: control
            for controls_dict in self.controls_handler.data.values()
            for control_id, control in controls_dict.items()
            if any(w in self._xml_filename for w in control.get("window", []))
        }

        self.listitems = {}
        self.dynamic_controls = {}

        for cid, ctrl in filtered_controls.items():
            if ctrl.get("control_type") == "listitem":
                self.listitems[cid] = ctrl
            elif "dynamic_linking" in ctrl:
                self.dynamic_controls[cid] = ctrl

    def _format_and_localize(self, mapping_key, idx, raw):
        """
        Substitute any {metadata} tokens in `raw` via runtime_state,
        then run infolabel() if it still begins with a Kodi $INFO reference.
        """
        formatted = self.runtime_manager.format_metadata(mapping_key, idx, raw)
        return infolabel(formatted) if formatted.startswith("$") else formatted

    def onInit(self):
        """
        Initializes controls and binds handlers. Applies initial visibility logic.
        """
        self.description_label = self.getControl(6)
        self.list_container = self.getControl(100)
        self.btn_add = self.getControl(410)
        self.btn_delete = self.getControl(411)
        self.btn_up = self.getControl(412)
        self.btn_down = self.getControl(413)

        # Management buttons visible if a special 'mapping preset' control is included
        has_preset = any(
            ctrl
            for ctrl in self.dynamic_controls.values()
            if ctrl.get("mapping") and "field" not in ctrl
        )
        for btn in (self.btn_add, self.btn_delete, self.btn_up, self.btn_down):
            btn.setVisible(has_preset)

        # Populate list
        for idx, (cid, item) in enumerate(self.listitems.items()):
            label = self._format_and_localize(
                item["mapping"], idx, item.get("label", "")
            )
            li = xbmcgui.ListItem(label=label)
            li.setProperty("content_id", cid)
            icon = item.get("icon")
            li.setArt({item.get("icon", "DefaultCopacetic.png"): icon})
            self.list_container.addItem(li)

        # Create handlers
        for control_id, control in self.dynamic_controls.items():
            cid = control.get("id")
            if cid is None:
                log(f"Skipping dynamic control {control_id}: missing 'id'")
                continue
            try:
                instance = self.getControl(cid)
                self.control_instances[control_id] = instance
                handler = DynamicControlFactory.create_handler(
                    control,
                    self.getControl,
                    self.runtime_manager,
                )
                if handler:
                    handler.parent = self
                    self.handlers[control_id] = handler
            except RuntimeError as e:
                log(
                    f"Warning: Control ID {id} ({control_id}) not found in XML layout: {e}"
                )

        # Initial state
        if self.listitems:
            self.container_position = -1
            current_focus = self.list_container.getId()
            execute(f"SetFocus({current_focus})")
            self.list_container.selectItem(0)
            self.onListScroll(current_focus)

    def onAction(self, action):
        """
        Called by Kodi when a user performs an action (e.g., movement, selection).
        Propagates action to each handler, updates focus and visibility.

        :param action: xbmcgui.Action object representing the user's input.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        a_id = action.getId()
        current_focus = self.getFocusId()
        requested_focus_change = None

        # List or handler interactions
        if current_focus == self.list_container.getId():
            self.onListScroll(current_focus)
        else:
            for handler in self.handlers.values():
                handler.handle_interaction(
                    self.current_listitem,
                    self.container_position,
                    self.getFocusId(),
                    a_id,
                )
                if hasattr(handler, "focus_target_id"):
                    requested_focus_change = handler.focus_target_id
                    del handler.focus_target_id

            if requested_focus_change:
                execute(f"Control.SetFocus({requested_focus_change})")
                current_focus = requested_focus_change

            for handler in self.handlers.values():
                handler.update_visibility(
                    self.current_listitem,
                    self.container_position,
                    current_focus,
                )
        # Management buttons
        if a_id == ACTION_SELECT_ITEM:
            idx = self.container_position
            mapping_key = self.listitems[self.current_listitem]["mapping"]

            if current_focus == self.btn_add.getId():
                preset_ctrl = next(
                    h
                    for h in self.handlers.values()
                    if h.control.get("mapping") and "field" not in h.control
                )
                preset_ctrl.handle_interaction(
                    self.current_listitem, idx, current_focus, ACTION_SELECT_ITEM
                )
                self._refresh_list()
                return

            if current_focus == self.btn_delete.getId():
                self.runtime_manager.delete_mapping_item(mapping_key, idx)
                self.container_position = max(0, idx - 1)
                self._refresh_list()
                return

            if current_focus == self.btn_up.getId():
                return self._on_move_up()

            if current_focus == self.btn_down.getId():
                return self._on_move_down()

        super().onAction(action)

    def onListScroll(self, current_focus):
        """
        Update dynamic controls when the list selection changes.

        :param current_focus: ID of the currently focused control.
        """
        index = self.list_container.getSelectedPosition()
        if index < 0 or index == self.container_position:
            return

        self.container_position = index
        cid = self.list_container.getListItem(index).getProperty("content_id")
        self.current_listitem = cid

        for handler in self.handlers.values():
            handler.update_value(self.current_listitem, self.container_position)
            handler.update_visibility(
                self.current_listitem,
                self.container_position,
                current_focus,
            )

        item = self.listitems[cid]
        desc = self._format_and_localize(
            item["mapping"],
            index,
            item.get("description", ""),
        )
        self.description_label.setText(desc or "")

    def onMappingItemChanged(self):
        for handler in self.handlers.values():
            handler.refresh_after_mapping_item_change(
                self.current_listitem, self.container_position, self.getFocusId()
            )

        li = self.list_container.getListItem(self.container_position)
        item_def = self.listitems[self.current_listitem]
        for attr, setter in (
            ("label", li.setLabel),
            ("description", self.description_label.setText),
        ):
            raw = item_def.get(attr, "")
            text = self._format_and_localize(
                item_def["mapping"], self.container_position, raw
            )
            resolved = infolabel(text) if text.startswith("$") else text
            setter(resolved or "")

    def _refresh_list(self):
        """Rebuild the entire list from runtime_state, restore selection, and re-sync controls."""
        items = list(self.listitems.items())
        old = self.container_position
        self.list_container.reset()

        for idx, (cid, item) in enumerate(items):
            label = self._format_and_localize(
                item["mapping"], idx, item.get("label", "")
            )
            li = xbmcgui.ListItem(label=label)
            li.setProperty("content_id", cid)
            icon = item.get("icon", "DefaultCopacetic.png")
            li.setArt({icon: icon})
            self.list_container.addItem(li)

        # restore selection
        size = self.list_container.size()
        sel = old if 0 <= old < size else 0
        self.list_container.selectItem(sel)
        self.container_position = sel
        self.current_listitem = self.list_container.getListItem(sel).getProperty(
            "content_id"
        )
        # re-sync
        self.onListScroll(self.getFocusId())

    def _refresh_list_row(self, idx):
        """Redraw the label and icon of list-row `idx` based on the current runtime_state."""
        li = self.list_container.getListItem(idx)
        cid = li.getProperty("content_id")
        item_def = self.listitems[cid]
        raw = item_def.get("label", "")
        new_label = self._format_and_localize(item_def["mapping"], idx, raw)
        li.setLabel(new_label)

    def _move(self, delta):
        """Move slot at current position forward or backward by a given delta."""
        old = self.container_position
        new = old + delta
        if new < 0 or new >= self.list_container.size():
            return
        # swap in JSON
        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.swap_mapping_items(mk, old, new)

        # swap two UI rows
        self._refresh_list_row(old)
        self._refresh_list_row(new)

        # advance focus
        self.container_position = new
        li = self.list_container.getListItem(new)
        self.list_container.selectItem(new)
        self.current_listitem = li.getProperty("content_id")

        # update the dynamic controls & bottom description for the new slot
        for h in self.handlers.values():
            h.update_value(self.current_listitem, self.container_position)
            h.update_visibility(
                self.current_listitem,
                self.container_position,
                self.getFocusId(),
            )
            
        item = self.listitems[self.current_listitem]
        desc = self._format_and_localize(
            item["mapping"], self.container_position, item.get("description", "")
        )
        self.description_label.setText(desc or "")

    def _on_move_up(self):
        self._move(-1)

    def _on_move_down(self):
        self._move(+1)
