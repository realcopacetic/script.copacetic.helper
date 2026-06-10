# author: realcopacetic

import copy

import xbmcgui

from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.builders.templates import load_template_data
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    TEMPLATES,
    RUNTIME_STATE,
    infolabel,
)
from resources.lib.windows.control_factory import DynamicControlFactory
from resources.lib.windows.controls import ButtonHandler

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
        self.mapping = None
        self.controls_from = []
        self._xml_filename = xmlFilename.lower()

        mappings, configs_data, controls_data = load_template_data(TEMPLATES)
        self.runtime_manager = RuntimeStateManager(
            mappings=mappings,
            configs_data=configs_data,
            controls_data=controls_data,
            runtime_state_path=RUNTIME_STATE,
        )

        self.handlers = {}
        self.dynamic_controls = {}
        self.skin_strings_changed = False
        self._has_runtime = False
        self.container_position = -1
        self.current_listitem = None
        self._prev_focus_id = -1
        self._mgmt_buttons = None
        self._mgmt_ids = set()
        self._mgmt_map = {
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
        Called by Kodi on window init. Sets up controls and renders the
        initial list.
        """
        self._description_label = self.getControl(6)
        self._list_container = self.getControl(100)

        # Build listitems and refresh list
        self._scan_controls()
        self._build_dicts()
        self._runtime_state_snapshot = copy.deepcopy(self.runtime_manager.runtime_state)
        log.debug(
            f"DynamicEditor onInit → xml={self._xml_filename} "
            f"mapping={self.mapping} "
            f"controls_from={self.controls_from} "
            f"listitems={list(self.listitems)}"
        )
        if self.listitems:
            self.container_position = 0
            self.current_listitem = next(iter(self.listitems))
            self._list_container.selectItem(self.container_position)
        self._refresh_list()

        # Initiate management buttons if runtime expansion
        self._has_runtime = any(
            ctrl.get("mode") == "dynamic" for ctrl in self.dynamic_controls.values()
        )
        if self._has_runtime:
            try:
                self._mgmt_buttons = []
                for name, entry in self._mgmt_map.items():
                    btn = self.getControl(entry["id"])
                    setattr(self, name, btn)
                    self._mgmt_buttons.append(btn)
            except RuntimeError:
                log.debug("Management buttons not found; skipping.")
                self._mgmt_buttons = None
            else:
                for btn in self._mgmt_buttons:
                    btn.setVisible(True)
                self._mgmt_ids = {btn.getId() for btn in self._mgmt_buttons}

        # Attach handlers to dynamic controls
        for control_id, control in self.dynamic_controls.items():
            cid = control.get("id")
            if cid is None:
                log.debug(f"Skipping dynamic control {control_id}: missing 'id'")
                continue

            handler = DynamicControlFactory.create_handler(
                control,
                self.getControl,
                self.runtime_manager,
            )
            if handler:
                handler.parent = self
                self.handlers[control_id] = handler

        # Build focus-ID → handler index for direct dispatch
        self._handler_by_focus_id = {}
        for h in self.handlers.values():
            for fid in h.focus_ids:
                self._handler_by_focus_id[fid] = h

        # Set initial focus and refresh UI
        if not self.listitems and self._has_runtime:
            # Empty list (e.g. filtered view with no children) — auto-add
            self._on_add()
            if not self.listitems:
                self.close()
                return

        if self.listitems:
            log.execute(f"SetFocus({self._list_container.getId()})")
            self._refresh_ui(update_row=False)

    def _scan_controls(self) -> None:
        """
        One-time scan of resolved controls for this window. Rebrands
        borrowed controls to the session mapping and preserves their
        original mapping on ``source_mapping`` for native-vs-borrowed checks.ls.
        """
        self._runtime_tpls = {}
        self._static_tpls = {}

        sources = [self.mapping] + list(self.controls_from)
        filtered = self.runtime_manager.controls.for_mappings(sources)
        for cid, ctrl in filtered.items():
            # Rebrand borrowed controls to the session mapping; preserve
            # the original on source_mapping for native-vs-borrowed checks.
            ctrl = {
                **ctrl,
                "mapping": self.mapping,
                "source_mapping": ctrl.get("mapping"),
            }
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
                "mapping": tpl["mapping"],
            }
            for tpl in self._runtime_tpls.values()
            for source_idx, entry in enumerate(
                self.runtime_manager.runtime_state.get(tpl["mapping"], [])
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

    def _apply_row_visuals(self, li, item: dict, runtime_id: str) -> None:
        """
        Resolve and apply a row's label and icon via ``format_metadata``,
        so each supports a metadata, config, or override value identically.

        :param li: List item to populate.
        :param item: Merged listitem definition (template + entry).
        :param runtime_id: Stable id stored as the row's content_id.
        """
        li.setProperty("content_id", runtime_id)
        mk, idx = item["mapping"], item["runtime_index"]
        li.setLabel(
            self.runtime_manager.format_metadata(
                mk, idx, item.get("label", ""), localize=True
            )
            or ""
        )
        if raw_icon := item.get("icon"):
            icon = self.runtime_manager.format_metadata(mk, idx, raw_icon, localize=True)
            li.setArt({"icon": icon})

    def _refresh_list(self) -> None:
        """
        Rebuild the left-hand list from `self.listitems` and sync dynamic controls.
        """
        self._list_container.reset()
        for runtime_id, item in self.listitems.items():
            li = xbmcgui.ListItem()
            self._apply_row_visuals(li, item, runtime_id)
            self._list_container.addItem(li)

    def _refresh_list_row(self, idx: int) -> None:
        """
        Redraw the label and icon for row `idx` from runtime_state metadata.

        :param idx: Row index in the list control.
        """
        keys = list(self.listitems.keys())
        if idx < 0 or idx >= len(keys):
            return
        runtime_id = keys[idx]
        li = self._list_container.getListItem(idx)
        self._apply_row_visuals(li, self.listitems[runtime_id], runtime_id)

    def _refresh_ui(self, update_row: bool = True) -> None:
        """
        Update all dynamic handlers and bottom description for current slot.

        :param update_row: Flag determining whether the current row's label should be updated.
        """
        if self.current_listitem is None or self.current_listitem not in self.listitems:
            return

        for h in self.handlers.values():
            h.update_value()
            h.update_visibility(self.getFocusId())
        if update_row:
            self._refresh_list_row(self.container_position)

        item = self.listitems[self.current_listitem]
        desc = self.runtime_manager.format_metadata(
            item["mapping"],
            self._source_index,
            item.get("description", ""),
            localize=True,
        )
        self._description_label.setText(desc or "")

    def _update_mgmt_buttons(self) -> None:
        """Enable/disable management buttons based on list position and size."""
        if not self._has_runtime or not self._mgmt_buttons:
            return

        has_items = bool(self.listitems)
        n = len(self.listitems)
        self.btn_delete.setEnabled(n > 1)
        self.btn_up.setEnabled(has_items and self.container_position > 0)
        self.btn_down.setEnabled(has_items and self.container_position < n - 1)

    def _refresh_handlers_after_mapping_change(self) -> None:
        """
        Re-evaluate all handler values and visibility after a preset change,
        resetting any field values that are no longer valid.
        """
        for h in self.handlers.values():
            h.refresh_after_mapping_item_change(self.getFocusId())
        self._refresh_list_row(self.container_position)

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
        prev_focus = self._prev_focus_id

        # Move Up/Down on management buttons
        if (
            a_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN)
            and current_focus in self._mgmt_ids
        ):
            old = self.container_position
            new = (
                max(0, old - 1)
                if a_id == ACTION_MOVE_UP
                else min(self._list_container.size() - 1, old + 1)
            )
            self._list_container.selectItem(new)
            self._on_list_scroll()
            return

        # List or handler interactions
        if current_focus == self._list_container.getId():
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
                    focused_handler.handle_interaction(prev_focus, a_id)
                    if focused_handler.focus_target_id is not None:
                        requested_focus = focused_handler.focus_target_id
                        focused_handler.focus_target_id = None

                if requested_focus:
                    log.execute(f"Control.SetFocus({requested_focus})")
                    current_focus = requested_focus

                for h in self.handlers.values():
                    h.update_visibility(current_focus)

            # Description — always update (mgmt buttons have descriptions too)
            focused_handler = (
                self._handler_by_focus_id.get(current_focus)
                if has_valid_selection
                else None
            )
            if focused_handler and focused_handler.description:
                desc = self.runtime_manager.format_metadata(
                    focused_handler.mapping_key,
                    self._source_index,
                    focused_handler.description,
                    localize=True,
                )
            else:
                desc = next(
                    (
                        entry["description"]
                        for entry in self._mgmt_map.values()
                        if entry["id"] == current_focus
                    ),
                    "",
                )
            self._description_label.setText(desc)

            # Management buttons — outside selection guard so Add works on empty lists
            if a_id == ACTION_SELECT_ITEM and self._mgmt_buttons:
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
            if current_focus != self._list_container.getId():
                log.execute(f"Control.SetFocus({self._list_container.getId()})")
                return  # don't fall through to super

            return self._on_close()

        self._prev_focus_id = current_focus
        super().onAction(action)

    def _on_list_scroll(self) -> None:
        """Handle user scrolling in the left list."""
        idx = self._list_container.getSelectedPosition()
        if idx < 0 or idx == self.container_position:
            return

        self.container_position = idx
        content_id = self._list_container.getListItem(idx).getProperty("content_id")
        if not content_id or content_id not in self.listitems:
            return  # placeholder row — don't update handlers

        self.current_listitem = content_id
        self._update_mgmt_buttons()
        self._refresh_ui()

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

        # Find the governing handler. Prefer one native to the session
        # mapping; fall back to a borrowed one if none is native.
        governors = [
            h
            for h in self.handlers.values()
            if h.control.get("role") in ("item_picker", "add_action")
        ]
        governing = next(
            (h for h in governors if h.control.get("source_mapping") == self.mapping),
            None,
        ) or next(iter(governors), None)

        # Phase 1: Dialog before insert — determines preset and/or field data
        chosen = "custom"
        browse_result = None
        then_data = None

        if governing:
            dialog_result = governing.run_preflight_dialog()
            if dialog_result is None:
                return
            result, cfg = dialog_result

            if governing.control.get("role") == "item_picker":
                if not isinstance(result, int) or result < 0:
                    return
                chosen = cfg["items"][result]

                # Optional chained action declared per-item on the picker.
                # If the chosen item maps to a handler name, run that handler's
                # onclick action (e.g. browse, input, select, colorpicker)
                # before inserting. User cancel of the chained action = no
                # insert.
                then_map = governing.control.get("onclick", {}).get("then", {})
                then_name = then_map.get(chosen)
                log.debug(
                    f"_on_add then lookup: name={then_name!r}, "
                    f"handlers={list(self.handlers.keys())}"
                )
                then_handler = self.handlers.get(then_name) if then_name else None
                if isinstance(then_handler, ButtonHandler):
                    then_dialog = then_handler.run_preflight_dialog()
                    if then_dialog is None:
                        return
                    then_result, then_cfg = then_dialog
                    if then_result is None:
                        return
                    then_data = (then_handler, then_result, then_cfg)
            else:
                if result is None:
                    return
                browse_result = result

        # Phase 2: Insert entry
        source_insert = self.runtime_manager.insert_position_for(
            mk,
            self.parent_filter,
            self._source_index if self.current_listitem else None,
        )

        extra = {"parent": self.parent_filter} if self.parent_filter else None
        new_entry = self.runtime_manager.insert_mapping_item(
            mk, chosen, source_insert, extra_fields=extra
        )

        new_id = new_entry["runtime_id"]

        # Select the new entry first — handlers resolve their target entry
        # through the editor's selection state, so this must precede apply.
        self.current_listitem = new_id
        self._build_dicts()

        # Phase 3: Apply browse data (add_action only — picker seeds via metadata)
        if browse_result is not None:
            governing.apply_result(browse_result, cfg)

        # Phase 3b: Apply picker chained action result (if any)
        if then_data is not None:
            handler, result, handler_cfg = then_data
            handler.apply_result(result, handler_cfg)

        # Re-sync listitem visuals with any fields the applies just wrote
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
        Delete the selected entry, prune orphaned children across other
        mappings, then re-anchor selection.
        """
        self.runtime_manager.reload_state()

        mk = self.listitems[self.current_listitem]["mapping"]
        self.runtime_manager.delete_mapping_item(mk, self._source_index)

        # Clean up children that referenced the deleted entry
        for other_key in self.runtime_manager.runtime_state:
            if other_key != mk:
                self.runtime_manager.delete_orphans(other_key)

        self._build_dicts()

        if not self.listitems:
            self.current_listitem = None
            self._on_close()
            return

        if self.container_position >= len(self.listitems):
            self.container_position = len(self.listitems) - 1

        self._refresh_list()
        self.current_listitem = list(self.listitems)[self.container_position]
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
        self._list_container.selectItem(new_display)

    def _on_reset(self) -> None:
        """
+        Reset entries to defaults after user confirmation. Scoped to
+        parent_filter when set; otherwise resets the whole mapping.
        """
        confirmed = xbmcgui.Dialog().yesno(
            "Reset to defaults",
            "This will reset all entries.\n\nAre you sure you want to continue?",
        )
        if not confirmed:
            return

        self.runtime_manager.reload_state()

        mk = self.listitems[self.current_listitem]["mapping"]
        if self.parent_filter:
            mapping = self.runtime_manager.mappings.get(mk, {})
            metadata = mapping.get("metadata", {})
            default_order = mapping.get("default_order") or mapping.get("items", [])
            parent_item = self.runtime_manager.mapping_item_for_runtime_id(
                self.parent_filter
            )
            for item in list(self.listitems.values()):
                self.runtime_manager.delete_mapping_item(mk, item["runtime_index"])
            for mi in default_order:
                if metadata.get(mi, {}).get("parent") == parent_item:
                    self.runtime_manager.insert_mapping_item(
                        mk, mi, extra_fields={"parent": self.parent_filter}
                    )
        else:
            self.runtime_manager.reset_runtime_state_for(mk)

        self._build_dicts()
        if not self.listitems:
            self.current_listitem = None
            self._on_close()
            return

        self._refresh_list()
        self.container_position = 0
        self.current_listitem = next(iter(self.listitems))
        self._finalize_selection(mapping_changed=True, list_rebuilt=True)

    def _on_close(self) -> None:
        """
        Close the modal. 
        Rebuild logic runs in dynamic_settings_window after doModal() returns.
        """
        self.close()

    def _finalize_selection(
        self, mapping_changed: bool = False, list_rebuilt: bool = False
    ) -> None:
        """
        Common tail after any structural change: reselect → optional
        mapping_item_changed → UI refresh. Caller must handle the state write,
        ``_build_dicts``, position/current_listitem, and list rebuild.

        :param mapping_changed: True if the entry's preset changed.
        :param list_rebuilt: True if the caller already called ``_refresh_list``.
        """
        if self.listitems:
            self._list_container.selectItem(self.container_position)

        if mapping_changed:
            # Picker path calls _refresh_handlers_after_mapping_change directly, so
            # that method must validate+render as a unit. _on_add/_on_reset hit both
            # paths — a redundant pass per handler, but it's microseconds.
            self._refresh_handlers_after_mapping_change()

        self._update_mgmt_buttons()
        self._refresh_ui(update_row=not list_rebuilt)

    def _seed_metadata(self) -> None:
        """
        Rebuild the current runtime entry for its newly-picked preset.
        Preserves runtime_id and parent; everything else regenerates
        from metadata + config_field defaults (same path as insert).
        """
        item = self.listitems.get(self.current_listitem)
        if not item:
            return
        mk = item["mapping"]
        idx = self._source_index
        existing = self.runtime_manager.runtime_state.get(mk, [])
        if not 0 <= idx < len(existing):
            return
        new_preset = existing[idx]["mapping_item"]
        preserve = {
            "runtime_id": existing[idx]["runtime_id"],
            **({"parent": existing[idx]["parent"]} if "parent" in existing[idx] else {}),
        }
        rebuilt = self.runtime_manager.rebuild_mapping_item(
            mk, new_preset, idx, preserve=preserve
        )
        if rebuilt is None:
            log.debug(f"_seed_metadata: rebuild failed for {mk}[{idx}]={new_preset}")

