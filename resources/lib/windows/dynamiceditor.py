# author: realcopacetic

import copy
from pathlib import Path

import xbmcgui

from resources.lib.builders.builder_config import BUILDER_MAPPINGS
from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import (
    CONFIGS,
    CONTROLS,
    RUNTIME_STATE,
    SKINEXTRAS,
    infolabel,
)
from resources.lib.windows.control_factory import DynamicControlFactory


class DynamicEditor(xbmcgui.WindowXMLDialog):
    """
    A dynamic skin settings editor window that adapts controls based on focus and runtime state.
    """

    def __init__(
        self, xmlFilename: str, skinPath: str, defaultSkin: str, defaultRes: str
    ) -> None:
        """
        Initialize the editor and prepare handlers for dynamic/static controls.

        :param xmlFilename: Name of the active XML window file.
        :param skinPath: Path to the current skin directory.
        :param defaultSkin: Name of the default skin.
        :param defaultRes: Default resolution.
        """
        super().__init__()
        self.parent_filter = None
        self.mapping_override = None
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
        self.dynamic_controls = {}
        self.skin_strings_changed = False
        self.has_runtime = False
        self.container_position = -1
        self.current_listitem = None
        self.prev_focus_id = -1
        self.mgmt_buttons = None
        self.mgmt_ids = set()
        self.mgmt_map = {
            "btn_add": {"id": 410, "description": "Add a new entry."},
            "btn_delete": {"id": 411, "description": "Delete the selected entry."},
            "btn_up": {"id": 412, "description": "Move the selected entry up."},
            "btn_down": {"id": 413, "description": "Move the selected entry down."},
            "btn_reset": {"id": 414, "description": "Reset all entries to defaults."},
            "btn_close": {"id": 415, "description": "Save and close."},
        }

    @property
    def _source_index(self) -> int:
        """
        Map the current display position to the source index in runtime state.
        When parent_filter is active, these may differ.

        :return: Index into the full runtime state list.
        """
        if self.current_listitem and self.current_listitem in self.listitems:
            return self.listitems[self.current_listitem]["runtime_index"]
        return self.container_position

    def onInit(self) -> None:
        """
        Called when the window is initialized by Kodi.

        Sets up controls, builds and displays the initial list.
        """
        log.debug(f"DynamicEditor onInit: xml={self._xml_filename} mapping={self.mapping_override}")

        self.description_label = self.getControl(6)
        log.debug("got description_label")
        self.list_container = self.getControl(100)
        log.debug("got list_container")

        # Build listitems and refresh list
        self._scan_controls()
        log.debug(f"scanned: runtime_tpls={list(self._runtime_tpls)} static_tpls={list(self._static_tpls)} dynamic={list(self.dynamic_controls)}")
        self._build_dicts()
        log.debug(f"built dicts: listitems={list(self.listitems)}")
        self._runtime_state_snapshot = copy.deepcopy(self.runtime_manager.runtime_state)
        log.debug("snapshot done")

        if self.listitems:
            self.container_position = 0
            self.current_listitem = next(iter(self.listitems))
            self.list_container.selectItem(self.container_position)
        self._refresh_list()

        # Initiate management buttons if runtime expansion
        self.has_runtime = any(
            ctrl.get("mode") == "dynamic" for ctrl in self.dynamic_controls.values()
        )
        if self.has_runtime:
            try:
                self.mgmt_buttons = []
                for name, entry in self.mgmt_map.items():
                    btn = self.getControl(entry["id"])
                    setattr(self, name, btn)
                    self.mgmt_buttons.append(btn)
            except RuntimeError:
                log.debug("Management buttons not found; skipping.")
                self.mgmt_buttons = None
            else:
                for btn in self.mgmt_buttons:
                    btn.setVisible(True)
                self.mgmt_ids = {btn.getId() for btn in self.mgmt_buttons}

        # Attach handlers to dynamic controls
        for control_id, control in self.dynamic_controls.items():
            cid = control.get("id")
            if cid is None:
                log.debug(f"Skipping dynamic control {control_id}: missing 'id'")
                continue
            try:
                handler = DynamicControlFactory.create_handler(
                    control,
                    self.getControl,
                    self.runtime_manager,
                )
                if handler:
                    handler.parent = self
                    self.handlers[control_id] = handler
            except RuntimeError as e:
                log.warning(
                    f"Warning: Control ID {cid} ({control_id}) not found in XML layout: {e}"
                )

        # Build focus-ID → handler index for direct dispatch
        self._handler_by_focus_id = {}
        for h in self.handlers.values():
            for fid in h.focus_ids:
                self._handler_by_focus_id[fid] = h

        # Set initial focus and refresh UI
        if not self.listitems and self.has_runtime:
            # Empty list (e.g. filtered view with no children) — auto-add
            self._on_add()
            if not self.listitems:
                self.close()
                return

        if self.listitems:
            log.execute(f"SetFocus({self.list_container.getId()})")
            self._refresh_ui(update_row=False)

    def onAction(self, action: xbmcgui.Action) -> None:
        """
        Called by Kodi when the user performs an action.
        Routes interactions to list or control handlers and management buttons.

        :param action: xbmcgui.Action object.
        """
        from xbmcgui import (
            ACTION_MOVE_DOWN,
            ACTION_MOVE_UP,
            ACTION_NAV_BACK,
            ACTION_PREVIOUS_MENU,
            ACTION_SELECT_ITEM,
        )

        a_id = action.getId()
        current_focus = self.getFocusId()
        prev_focus = self.prev_focus_id

        # Move Up/Down on management buttons
        if (
            a_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN)
            and current_focus in self.mgmt_ids
        ):
            old = self.container_position
            new = (
                max(0, old - 1)
                if a_id == ACTION_MOVE_UP
                else min(self.list_container.size() - 1, old + 1)
            )
            self.list_container.selectItem(new)
            self._on_list_scroll()
            return

        # List or handler interactions
        if current_focus == self.list_container.getId():
            self._on_list_scroll()
        else:
            has_valid_selection = (
                self.current_listitem is not None
                and self.current_listitem in self.listitems
            )

            # Handler interactions — only with valid selection
            if has_valid_selection:
                requested_focus = None
                focused_handler = self._handler_by_focus_id.get(prev_focus)
                if focused_handler:
                    focused_handler.handle_interaction(
                        self.current_listitem,
                        self._source_index,
                        prev_focus,
                        a_id,
                    )
                    if focused_handler.focus_target_id is not None:
                        requested_focus = focused_handler.focus_target_id
                        focused_handler.focus_target_id = None

                if requested_focus:
                    log.execute(f"Control.SetFocus({requested_focus})")
                    current_focus = requested_focus

                for h in self.handlers.values():
                    h.update_visibility(
                        self.current_listitem,
                        self._source_index,
                        current_focus,
                    )

            # Description — always update (mgmt buttons have descriptions too)
            focused_handler = (
                self._handler_by_focus_id.get(current_focus)
                if has_valid_selection
                else None
            )
            if focused_handler and focused_handler.description:
                desc = self._format_and_localize(
                    focused_handler.mapping_key,
                    self._source_index,
                    focused_handler.description,
                )
            else:
                desc = next(
                    (
                        entry["description"]
                        for entry in self.mgmt_map.values()
                        if entry["id"] == current_focus
                    ),
                    "",
                )
            self.description_label.setText(desc)

            # Management buttons — outside selection guard so Add works on empty lists
            if a_id == ACTION_SELECT_ITEM and self.mgmt_buttons:
                if current_focus == self.btn_add.getId():
                    return self._on_add()

                if has_valid_selection:
                    if current_focus == self.btn_delete.getId():
                        return self._on_delete()

                    if current_focus == self.btn_up.getId():
                        return self._on_move(-1)

                    if current_focus == self.btn_down.getId():
                        return self._on_move(1)

                if current_focus == self.btn_reset.getId():
                    return self._on_reset()

                if current_focus == self.btn_close.getId():
                    return self._on_close()

        if a_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
            if current_focus != self.list_container.getId():
                log.execute(f"Control.SetFocus({self.list_container.getId()})")
                return  # don't fall through to super

            return self._on_close()

        self.prev_focus_id = current_focus
        super().onAction(action)

    def _scan_controls(self) -> None:
        """
        One-time scan of controls.json for this window.
        Separates listitems templates from dynamic controls.
        Called once in onInit.
        """
        self._runtime_tpls = {}
        self._static_tpls = {}

        filtered = {
            cid: ctrl
            for controls in self.controls_handler.data.values()
            for cid, ctrl in controls.items()
            if any(w in self._xml_filename for w in ctrl.get("window", []))
        }
        for cid, ctrl in filtered.items():
            if ctrl.get("control_type") == "listitem":
                bucket = (
                    self._runtime_tpls
                    if ctrl.get("mode") == "dynamic"
                    else self._static_tpls
                )
                bucket[cid] = ctrl
            else:
                self.dynamic_controls[cid] = ctrl

    def _build_dicts(self) -> None:
        """
        Rebuild listitem entries from runtime state, optionally filtered by parent.
        """
        runtime_items = {
            entry["runtime_id"]: {
                **tpl,
                **entry,
                "runtime_index": source_idx,
                "mapping": self.mapping_override or tpl.get("mapping"),
            }
            for tpl in self._runtime_tpls.values()
            for source_idx, entry in enumerate(
                self.runtime_manager.runtime_state.get(
                    self.mapping_override or tpl.get("mapping"), []
                )
            )
            if not self.parent_filter or entry.get("parent") == self.parent_filter
        }
        self.listitems = {
            **runtime_items,
            **{
                cid: {
                    **tpl,
                    "runtime_index": idx,
                    "runtime_id": cid,
                }
                for idx, (cid, tpl) in enumerate(self._static_tpls.items())
            },
        }

    def _format_and_localize(self, mapping_key: str, idx: int, raw: str) -> str:
        """
        Format placeholders in `raw` from metadata and translate Kodi infolabels.

        :param mapping_key: Mapping group key.
        :param idx: Index in the runtime list.
        :param raw: Template string containing {metadata} tokens.
        :return: Localized, formatted string.
        """
        formatted = (
            raw
            if "{" not in raw
            else self.runtime_manager.format_metadata(mapping_key, idx, raw)
        )
        return infolabel(formatted) if formatted.startswith("$") else formatted

    def _refresh_list(self) -> None:
        """
        Rebuild the left-hand list from `self.listitems` and sync dynamic controls.
        """
        self.list_container.reset()
        for runtime_id, item in self.listitems.items():
            label = self._format_and_localize(
                item["mapping"], item["runtime_index"], item.get("label", "")
            )
            li = xbmcgui.ListItem(label=label)
            li.setProperty("content_id", runtime_id)
            if icon := item.get("icon"):
                li.setArt({"icon": icon})
            self.list_container.addItem(li)

    def _refresh_list_row(self, idx: int) -> None:
        """
        Redraw the label and icon for row `idx` from runtime_state metadata.

        :param idx: Row index in the list control.
        """
        keys = list(self.listitems.keys())
        if idx < 0 or idx >= len(keys):
            return
        runtime_id = keys[idx]
        item_def = self.listitems[runtime_id]
        li = self.list_container.getListItem(idx)
        li.setProperty("content_id", runtime_id)

        raw = item_def.get("label", "")
        new_lbl = self._format_and_localize(
            item_def["mapping"], item_def["runtime_index"], raw
        )
        li.setLabel(new_lbl or "")
        if icon := item_def.get("icon"):
            li.setArt({"icon": icon})

    def _refresh_ui(self, update_row: bool = True) -> None:
        """
        Update all dynamic handlers and bottom description for current slot.

        :param update_row: Flag determining whether the current row's label should be updated.
        """
        if self.current_listitem is None or self.current_listitem not in self.listitems:
            return

        for h in self.handlers.values():
            h.update_value(self.current_listitem, self._source_index)
            h.update_visibility(
                self.current_listitem,
                self._source_index,
                self.getFocusId(),
            )
        if update_row:
            self._refresh_list_row(self.container_position)

        item = self.listitems[self.current_listitem]
        desc = self._format_and_localize(
            item["mapping"], self._source_index, item.get("description", "")
        )
        self.description_label.setText(desc or "")

    def _update_mgmt_buttons(self) -> None:
        """Enable/disable management buttons based on list position and size."""
        if not self.has_runtime or not self.mgmt_buttons:
            return

        has_items = bool(self.listitems)
        n = len(self.listitems)
        self.btn_delete.setEnabled(n > 1)
        self.btn_up.setEnabled(has_items and self.container_position > 0)
        self.btn_down.setEnabled(has_items and self.container_position < n - 1)

    def _on_list_scroll(self) -> None:
        """Handle user scrolling in the left list."""
        idx = self.list_container.getSelectedPosition()
        if idx < 0 or idx == self.container_position:
            return

        self.container_position = idx
        content_id = self.list_container.getListItem(idx).getProperty("content_id")
        if not content_id or content_id not in self.listitems:
            return  # placeholder row — don't update handlers

        self.current_listitem = content_id
        self._update_mgmt_buttons()
        self._refresh_ui()

    def _seed_metadata(self) -> None:
        """
        Write metadata fields from the current preset into runtime state.
        Skips the ``parent`` field to avoid overwriting parent references.
        """
        item = self.listitems.get(self.current_listitem)
        if not item:
            return
        mk = item["mapping"]
        new_preset = self.runtime_manager.get_runtime_setting(
            mk, self._source_index, "mapping_item"
        )
        metadata = (
            self.runtime_manager.mappings.get(mk, {})
            .get("metadata", {})
            .get(new_preset, {})
        )
        updates = {k: v for k, v in metadata.items() if k != "parent"}
        if updates:
            try:
                self.runtime_manager.update_runtime_settings_batch(
                    mk, self._source_index, updates
                )
            except IndexError:
                pass

    def _refresh_handlers_after_mapping_change(self) -> None:
        """
        Re-evaluate all handler values and visibility after a preset change,
        resetting any field values that are no longer valid.
        """
        for h in self.handlers.values():
            h.refresh_after_mapping_item_change(
                self.current_listitem, self._source_index, self.getFocusId()
            )
        self._refresh_list_row(self.container_position)

    def _finalize_selection(
        self, mapping_changed: bool = False, list_rebuilt: bool = False
    ) -> None:
        """
        Common tail after any structural change. Caller is responsible for:
        - writing to runtime state
        - calling _build_dicts()
        - setting self.container_position and self.current_listitem
        - rebuilding/patching the list if needed

        This method handles: reselect → optional mapping_item_changed → UI refresh.
        """
        if self.listitems:
            self.list_container.selectItem(self.container_position)

        if mapping_changed:
            self._refresh_handlers_after_mapping_change()

        self._update_mgmt_buttons()
        self._refresh_ui(update_row=not list_rebuilt)

    def _on_add(self) -> None:
        """
        Insert a new entry. Runs the governing handler's dialog (item_picker
        or add_action) before inserting, so nothing is written on cancel.
        """
        if self.current_listitem:
            mk = self.listitems[self.current_listitem]["mapping"]
        else:
            mk = next(
                (ctrl["mapping"] for ctrl in self.dynamic_controls.values()),
                None,
            )
            if not mk:
                return

        self.runtime_manager.reload_state()

        # Find the governing handler — mutually exclusive
        governing = next(
            (
                h
                for h in self.handlers.values()
                if h.control.get("role") in ("item_picker", "add_action")
            ),
            None,
        )

        # Phase 1: Dialog before insert — determines preset and/or field data
        chosen = "custom"
        browse_result = None

        if governing:
            dialog_result = governing.run_preflight_dialog()
            if dialog_result is None:
                return
            result, cfg = dialog_result

            if governing.control.get("role") == "item_picker":
                if not isinstance(result, int) or result < 0:
                    return
                chosen = cfg["items"][result]
            else:
                if result is None:
                    return
                browse_result = result

        # Phase 2: Insert entry
        if self.current_listitem:
            source_insert = self._source_index + 1
        elif self.parent_filter:
            flat = self.runtime_manager.runtime_state.get(mk, [])
            # Try after last existing sibling
            last_sibling = next(
                (
                    i
                    for i in range(len(flat) - 1, -1, -1)
                    if flat[i].get("parent") == self.parent_filter
                ),
                None,
            )
            if last_sibling is not None:
                source_insert = last_sibling + 1
            else:
                # No siblings yet — insert before the first child of any
                # parent that comes after ours in the parent mapping
                later_ids = self._later_parent_ids(mk)
                source_insert = next(
                    (i for i, e in enumerate(flat) if e.get("parent") in later_ids),
                    len(flat),
                )
        else:
            source_insert = len(self.runtime_manager.runtime_state.get(mk, []))

        extra = {"parent": self.parent_filter} if self.parent_filter else None
        new_entry = self.runtime_manager.insert_mapping_item(
            mk, chosen, source_insert, extra_fields=extra
        )

        new_id = new_entry["runtime_id"]

        # Phase 3: Apply browse data (add_action only — picker seeds via metadata)
        if browse_result is not None:
            governing.current_listitem = new_id
            governing.source_index = source_insert
            governing.apply_result(browse_result, cfg)

        # Set current selection before mapping_changed triggers _build_dicts
        self.current_listitem = new_id
        self._build_dicts()

        display_keys = list(self.listitems.keys())
        self.container_position = (
            display_keys.index(new_id) if new_id in display_keys else 0
        )

        self._refresh_list()
        # mapping_changed=True refreshes handlers (metadata already included
        # in the new entry via _build_default_entry — no _seed_metadata needed)
        self._finalize_selection(mapping_changed=True, list_rebuilt=True)

    def _on_delete(self) -> None:
        """
        Removes the currently selected item from runtime_state.json,
        self.listitems dictionary and Kodi UI. Then updates current
        listitem and container position.
        """
        self.runtime_manager.reload_state()

        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.delete_mapping_item(mk, self._source_index)

        # Clean up children that referenced the deleted entry
        for other_key in self.runtime_manager.runtime_state:
            if other_key != mk:
                self.runtime_manager.delete_orphans(mk, other_key)

        self._build_dicts()

        if not self.listitems:
            self.current_listitem = None
            self._on_close()
            return

        if self.container_position >= len(self.listitems):
            self.container_position = len(self.listitems) - 1

        self._refresh_list()
        li = self.list_container.getListItem(self.container_position)
        self.current_listitem = li.getProperty("content_id")
        self._finalize_selection(list_rebuilt=True)

    def _on_move(self, delta: int) -> None:
        """
        Move the current entry forward or backward by swapping with its neighbour.

        :param delta: Direction and distance to move (-1 = up, +1 = down).
        """
        if not self.current_listitem or self.current_listitem not in self.listitems:
            return

        self.runtime_manager.reload_state()

        display_keys = list(self.listitems.keys())
        old_display = self.container_position
        new_display = old_display + delta
        if new_display < 0 or new_display >= len(display_keys):
            return

        old_source = self._source_index
        new_source = self.listitems[display_keys[new_display]]["runtime_index"]

        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.swap_mapping_items(mk, old_source, new_source)
        self._build_dicts()
        self._refresh_list_row(old_display)
        self._refresh_list_row(new_display)

        self.container_position = new_display
        self.current_listitem = list(self.listitems.keys())[new_display]
        self._update_mgmt_buttons()
        self.list_container.selectItem(new_display)

    def _on_reset(self) -> None:
        """
        Reset all entries to defaults after user confirmation.
        Rebuilds the list and reselects the first item.
        """
        confirmed = xbmcgui.Dialog().yesno(
            "Reset to defaults",
            "This will reset all entries.\n\nAre you sure you want to continue?",
        )
        if not confirmed:
            return

        self.runtime_manager.reload_state()

        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.reset_runtime_state_for(mk)

        self._build_dicts()
        self._refresh_list()
        self.container_position = 0
        self.current_listitem = next(iter(self.listitems))
        self._finalize_selection(mapping_changed=True, list_rebuilt=True)

    def _on_close(self) -> None:
        """Trigger a runtime rebuild and close the window."""
        if self.parent_filter:
            # Child window — parent will handle rebuild on its own close
            self.close()
            return

        self.runtime_manager.reload_state()
        
        if (
            self.runtime_manager.runtime_state != self._runtime_state_snapshot
            or self.skin_strings_changed
        ):
            from resources.lib.builders.build_elements import BuildElements

            BuildElements(run_context="runtime")
            log.execute("ReloadSkin()")

        self.close()

    def _later_parent_ids(self, child_mapping: str) -> set[str]:
        """
        Return the set of runtime_ids for parent entries that come after
        self.parent_filter in the parent mapping's order.

        :param child_mapping: The child mapping key (used to skip self).
        :return: Set of runtime_ids for later parents, or empty set.
        """
        for key, entries in self.runtime_manager.runtime_state.items():
            if key == child_mapping or not isinstance(entries, list):
                continue
            for i, entry in enumerate(entries):
                if entry.get("runtime_id") == self.parent_filter:
                    return {e["runtime_id"] for e in entries[i + 1 :]}
        return set()
