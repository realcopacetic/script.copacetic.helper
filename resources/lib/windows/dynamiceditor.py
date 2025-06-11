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
    A dynamic skin settings editor window that adapts controls based on focus and runtime state.
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
        self.dynamic_controls = {}
        self.listitems = {}

    def _build_dicts(self):
        """
        Populate listitem templates and dynamic controls from JSON definitions.
        Scans controls.json for this window, separates static controls/listitems and dynamic controls.
        """
        filtered = {
            cid: ctrl
            for controls in self.controls_handler.data.values()
            for cid, ctrl in controls.items()
            if any(w in self._xml_filename for w in ctrl.get("window", []))
        }
        self.dynamic_controls = {
            cid: ctrl for cid, ctrl in filtered.items() if "dynamic_linking" in ctrl
        }
        tpl_entry = next(
            (
                (cid, ctrl)
                for cid, ctrl in filtered.items()
                if ctrl.get("control_type") == "listitem"
            ),
            None,
        )
        if not tpl_entry:
            self.listitems = {}
            return

        _, tpl = tpl_entry
        mapping_key = tpl["mapping"]
        entries = self.runtime_manager.runtime_state.get(mapping_key, [])
        for idx, entry in enumerate(entries):
            self.listitems[entry["mapping_item"]] = {
                k: (
                    self._format_and_localize(mapping_key, idx, v)
                    if isinstance(v, str)
                    else v
                )
                for k, v in tpl.items()
            }

    def _format_and_localize(self, mapping_key, idx, raw):
        """
        Format placeholders in `raw` from metadata and translate Kodi $INFO labels.

        :param mapping_key: Mapping group key.
        :param idx: Index in the runtime list.
        :param raw: Template string containing {metadata} tokens.
        :returns: Localized, formatted string.
        """
        formatted = self.runtime_manager.format_metadata(mapping_key, idx, raw)
        return infolabel(formatted) if formatted.startswith("$") else formatted

    def _refresh_list(self):
        """
        Rebuild the left-hand list from `self.listitems` and sync dynamic controls.
        """
        self.list_container.reset()
        for idx, (cid, item) in enumerate(self.listitems.items()):
            label = self._format_and_localize(
                item["mapping"], idx, item.get("label", "")
            )
            li = xbmcgui.ListItem(label=label)
            li.setProperty("content_id", cid)
            icon = item.get("icon", "DefaultCopacetic.png")
            li.setArt({icon: icon})
            self.list_container.addItem(li)

        self.list_container.selectItem(self.container_position)
        self._refresh_ui()

    def _refresh_ui(self):
        """
        Update all dynamic handlers and bottom description for current slot.
        """
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

    def __refresh_list_row(self, idx):
        """
        Redraw the label and icon for row `idx` from runtime_state metadata.

        :param idx: Row index in the list control.
        """
        li = self.list_container.getListItem(idx)
        mapping_item = list(self.listitems.keys())[idx]
        item_def = self.listitems[mapping_item]
        li.setProperty("content_id", mapping_item)
        raw = item_def.get("label", "")
        new_lbl = self._format_and_localize(item_def["mapping"], idx, raw)
        li.setLabel(new_lbl or "")
        icon = item_def.get("icon", "DefaultCopacetic.png")
        li.setArt({icon: icon})

    def onInit(self):
        """
        Called when the window is initialized by Kodi.

        Sets up controls, builds and displays the initial list.
        """
        self.description_label = self.getControl(6)
        self.list_container = self.getControl(100)
        self.btn_add = self.getControl(410)
        self.btn_delete = self.getControl(411)
        self.btn_up = self.getControl(412)
        self.btn_down = self.getControl(413)

        self.mgmt_ids = {
            b.getId()
            for b in (self.btn_add, self.btn_delete, self.btn_up, self.btn_down)
        }

        # Show management buttons if a preset-picker exists
        has_preset = any(
            ctrl
            for ctrl in self.dynamic_controls.values()
            if ctrl.get("mapping") and "field" not in ctrl
        )
        for btn in (self.btn_add, self.btn_delete, self.btn_up, self.btn_down):
            btn.setVisible(has_preset)

        # Build listitems and refresh UI
        self._build_dicts()
        self._refresh_list()

        # Attach handlers to dynamic controls
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

    def onAction(self, action):
        """
        Called by Kodi when the user performs an action.
        Routes interactions to list or control handlers and management buttons.
        
        :param action: xbmcgui.Action object.
        """
        from xbmcgui import ACTION_SELECT_ITEM, ACTION_MOVE_UP, ACTION_MOVE_DOWN

        a_id = action.getId()
        current_focus = self.getFocusId()

        # Move Up/Down on management buttons
        if a_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and current_focus in self.mgmt_ids:
            delta = -1 if a_id == ACTION_MOVE_UP else 1
            old = self.container_position
            new = max(0, min(self.list_container.size() - 1, old + delta))
            self.list_container.selectItem(new)
            self._on_list_scroll(self.list_container.getId())
            return

        # List or handler interactions
        if current_focus == self.list_container.getId():
            self._on_list_scroll(current_focus)
        else:
            requested_focus = None
            for h in self.handlers.values():
                h.handle_interaction(
                    self.current_listitem,
                    self.container_position,
                    self.getFocusId(),
                    a_id,
                )
                if hasattr(h, "focus_target_id"):
                    requested_focus = h.focus_target_id
                    del h.focus_target_id

            if requested_focus:
                execute(f"Control.SetFocus({requested_focus})")
                current_focus = requested_focus

            for h in self.handlers.values():
                h.update_visibility(
                    self.current_listitem,
                    self.container_position,
                    current_focus,
                )
        # Management buttons
        if a_id == ACTION_SELECT_ITEM:
            if current_focus == self.btn_add.getId():
                return self._on_add()

            if current_focus == self.btn_delete.getId():
                return self._on_delete()

            if current_focus == self.btn_up.getId():
                return self._on_move(-1)

            if current_focus == self.btn_down.getId():
                return self._on_move(+1)

        super().onAction(action)

    def _on_list_scroll(self, current_focus):
        """
        Handle user scrolling in the left list.

        :param current_focus: ID of the currently focused control.
        """
        idx = self.list_container.getSelectedPosition()
        if idx < 0 or idx == self.container_position:
            return

        self.container_position = idx
        self.current_listitem = self.list_container.getListItem(idx).getProperty(
            "content_id"
        )
        self._refresh_ui()

    def _on_mapping_item_changed(self):
        """
        Called when mapping_item is changed programmatically (add/delete/move).
        """
        for h in self.handlers.values():
            h.refresh_after_mapping_item_change(
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

    def _on_add(self):
        """
        Clone the current slot, insert it, then invoke the preset-picker handler.
        """
        from xbmcgui import ACTION_SELECT_ITEM

        idx = self.container_position
        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.insert_mapping_item(mk, idx, self.current_listitem)
        self._build_dicts()

        preset = next(
            h
            for h in self.handlers.values()
            if h.control.get("mapping") and "field" not in h.control
        )
        preset.handle_interaction(
            self.current_listitem, idx, self.getFocusId(), ACTION_SELECT_ITEM
        )

        self._refresh_list()

    def _on_delete(self):
        """
        Removes the currently selected item from runtime_state.json,
        self.listitems dictionary and Kodi UI. Then updates current
        listitem and container position.
        """
        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.delete_mapping_item(mk, self.container_position)
        self.listitems.pop(self.current_listitem, None)
        self.list_container.removeItem(self.container_position)

        new_pos = min(self.container_position, self.list_container.size() - 1)
        self.container_position = max(0, new_pos)
        self._refresh_list()

    def _on_move(self, delta):
        """Move slot at current position forward or backward by a given delta."""
        old = self.container_position
        new = old + delta
        if new < 0 or new >= self.list_container.size():
            return

        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.swap_mapping_items(mk, old, new)

        items = list(self.listitems.items())
        items[old], items[new] = items[new], items[old]
        self.listitems = dict(items)

        self.__refresh_list_row(old)
        self.__refresh_list_row(new)

        self.container_position = new
        self.list_container.selectItem(new)
