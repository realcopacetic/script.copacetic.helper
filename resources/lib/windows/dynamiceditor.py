# author: realcopacetic

import copy
import time
from functools import partial

import xbmcgui
from xbmcgui import (
    ACTION_MOUSE_LEFT_CLICK,
    ACTION_MOVE_DOWN,
    ACTION_MOVE_UP,
    ACTION_NAV_BACK,
    ACTION_PREVIOUS_MENU,
    ACTION_SELECT_ITEM,
)

from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.service.serve import ring
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, infolabel, window_property
from resources.lib.windows.control_factory import DynamicControlFactory
from resources.lib.windows.controls import ButtonHandler, LockedCalls


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
        self.host = None
        self.host_focus = None
        self.focus_item = None
        self.controls_from = []
        self.ring = None

        self.runtime_manager = RuntimeStateManager.from_templates()
        # Snapshot here, not in onInit — the post-doModal rebuild comparison
        # must work even if onInit aborts (e.g. contract controls missing
        # from the window XML).
        self._runtime_state_snapshot = copy.deepcopy(self.runtime_manager.runtime_state)

        self.handlers = {}
        self.dynamic_controls = {}
        self.container_position = -1
        self.current_listitem = None
        # What each row and the description show, so a refresh writes only changes
        self._rows_shown = {}
        self._description = None
        self._prev_focus_id = -1
        self._page_changed = False
        self._page_locked = False
        self._mgmt_buttons = []
        self._mgmt_ids = set()
        self._mgmt_map = {
            "btn_add": {
                "id": 410,
                "description": ADDON.getLocalizedString(32827),
                "action": self._on_add,
                "mutation": True,
                "needs_selection": False,
                "btn": None,
            },
            "btn_up": {
                "id": 411,
                "description": ADDON.getLocalizedString(32828),
                "action": lambda: self._on_move(-1),
                "mutation": True,
                "needs_selection": True,
                "btn": None,
            },
            "btn_down": {
                "id": 412,
                "description": ADDON.getLocalizedString(32829),
                "action": lambda: self._on_move(1),
                "mutation": True,
                "needs_selection": True,
                "btn": None,
            },
            "btn_delete": {
                "id": 413,
                "description": ADDON.getLocalizedString(32830),
                "action": self._on_delete,
                "mutation": True,
                "needs_selection": True,
                "btn": None,
            },
            "btn_reset": {
                "id": 414,
                "description": ADDON.getLocalizedString(32831),
                "action": self._on_reset,
                "mutation": False,
                "needs_selection": False,
                "btn": None,
            },
            "btn_close": {
                "id": 415,
                "description": ADDON.getLocalizedString(32832),
                "action": self._on_close,
                "mutation": False,
                "needs_selection": False,
                "btn": None,
            },
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
        # No valid selection: never fall back to container_position — under
        # parent_filter a display index is not a source index, so a write
        # through it would land on an arbitrary unfiltered entry.
        return -1

    def onInit(self) -> None:
        """
        Called by Kodi on window init. Sets up controls and renders the
        initial list.
        """
        window_property("editor_label", value=infolabel("System.CurrentWindow"))
        # Its own id, read while it is the top dialog: a picker it opens later is not
        self._window_id = str(xbmcgui.getCurrentWindowDialogId())
        self._description_label = self.getControl(6)
        self._list_container = self.getControl(100)

        # Colour contract: hidden labels name the palette roles. getControl() wraps
        # a skin label without its text, so read it as the topmost dialog's label.
        color_map = {"focused": (420, "FFFFFFFF"), "unfocused": (421, "80FFFFFF")}
        self._colors = {
            role: infolabel(f"Control.GetLabel({cid})").strip() or default
            for role, (cid, default) in color_map.items()
        }

        # Build listitems and refresh list
        self._scan_controls()
        self._build_dicts()
        if self.listitems:
            self.container_position = 0
            self.current_listitem = next(iter(self.listitems))
            if self.focus_item:
                for pos, (rid, entry) in enumerate(self.listitems.items()):
                    if entry.get("mapping_item") == self.focus_item:
                        self.container_position = pos
                        self.current_listitem = rid
                        break
        self._refresh_list()
        if self.listitems:
            self._list_container.selectItem(self.container_position)

        # Management buttons — reset/close are optional in every window;
        # mutation buttons (add/delete/move) are required in a governed one.
        # Every editor mapping is runtime-backed, so governor presence is
        # the sole gate: governed windows manage their entry list, seeded
        # windows edit fields on a fixed one.
        self._has_governor = any(
            ctrl.get("role") in ("item_picker", "add_action")
            for ctrl in self.dynamic_controls.values()
        )
        self._mgmt_buttons = []
        self._mgmt_ids = set()
        for entry in self._mgmt_map.values():
            if entry["mutation"]:
                if not self._has_governor:
                    continue
                entry["btn"] = self.getControl(entry["id"])
                self._mgmt_ids.add(entry["id"])
            else:
                try:
                    entry["btn"] = self.getControl(entry["id"])
                except RuntimeError:
                    continue
            self._mgmt_buttons.append(entry["btn"])

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

        # Empty list (e.g. filtered view with no children): a governed one adds.
        if not self.listitems and self._has_governor:
            self._on_add()
        # Still empty after a cancelled add, or no state row yet with no tab strip
        # to focus: no key could reach the window to close it.
        if not self.listitems and (self._has_governor or not self.host_focus):
            self.close()
            return

        if self.listitems:
            # Focus lands on the skin-declared host_focus, else on the list.
            if self.host_focus:
                log.execute(f"SetFocus({self.host_focus})")
                # onAction runs after Kodi has handled the key, so it acts on the
                # focus the last action left: the first press must find it here.
                self._prev_focus_id = int(self.host_focus)
            else:
                log.execute(f"SetFocus({self._list_container.getId()})")
            # Delete stays off on a one-entry list from the start, not only once moved
            self._update_mgmt_buttons()
            self._refresh_ui(update_row=False)

    def _scan_controls(self) -> None:
        """
        One-time scan of resolved controls for this window. Rebrands
        borrowed controls to the session mapping and preserves their
        original mapping on ``source_mapping`` for native-vs-borrowed checks.
        """
        self._runtime_tpls = {}

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
                self._runtime_tpls[cid] = ctrl
            else:
                self.dynamic_controls[cid] = ctrl

    def _build_dicts(self) -> None:
        """
        Rebuild listitem entries from runtime state, optionally filtered by parent.
        """
        # A stored label, icon or description reaches the row only through the
        # template's {token}, never as a template of its own: blank before **tpl.
        self.listitems = {
            entry["runtime_id"]: {
                **entry,
                "description": "",
                "icon": "",
                **tpl,
                "runtime_index": source_idx,
            }
            for tpl in self._runtime_tpls.values()
            for source_idx, entry in self.runtime_manager.live_rows(tpl["mapping"])
            if not self.parent_filter or entry.get("parent") == self.parent_filter
        }

    def _apply_row_visuals(
        self, li: xbmcgui.ListItem, item: dict, runtime_id: str, shown: dict
    ) -> bool:
        """
        Resolve a row's label and icon via ``format_metadata``, so each supports a
        metadata, config, or override value identically, and its properties; write
        only what differs from what the row shows.

        :param li: List item to populate.
        :param item: Merged listitem definition (template + entry).
        :param runtime_id: Stable id stored as the row's content_id.
        :param shown: What the row shows, updated in place.
        :return: Whether anything was written.
        """
        mk, idx = item["mapping"], item["runtime_index"]
        fmt = partial(self.runtime_manager.format_metadata, mk, idx, localize=True)
        label = fmt(item.get("label", "")) or ""
        # A row with no icon template keeps the art it has
        icon = fmt(raw_icon) if (raw_icon := item.get("icon")) else shown.get("icon")
        # Expose resolved entry (metadata + stored + config defaults) as properties
        properties = {"content_id": runtime_id} | {
            key: value
            for key, value in self.runtime_manager.resolved_entry(mk, idx).items()
            if isinstance(value, str)
        }
        shown_properties = shown.setdefault("properties", {})
        writes = [
            (li.setProperty, key, value)
            for key, value in properties.items()
            if shown_properties.get(key) != value
        ]
        if label != shown.get("label"):
            writes.append((li.setLabel, label))
        if icon != shown.get("icon"):
            writes.append((li.setArt, {"icon": icon}))
        for setter, *args in writes:
            LockedCalls.write(setter, *args)
        shown.update(label=label, icon=icon)
        shown_properties.update(properties)
        return bool(writes)

    def _refresh_list(self) -> None:
        """
        Rebuild the left-hand list from `self.listitems`, then ring the region the
        skin opted in to (``ring``), which follows the selected row.
        """
        self._list_container.reset()
        self._rows_shown = {}
        for idx, (runtime_id, item) in enumerate(self.listitems.items()):
            li = xbmcgui.ListItem()
            shown = self._rows_shown[idx] = {}
            self._apply_row_visuals(li, item, runtime_id, shown)
            self._list_container.addItem(li)
        self._ring()

    def _refresh_list_row(self, idx: int, moved: bool = False) -> None:
        """
        Redraw row `idx` where its label, icon or properties changed, then ring
        (``ring``) once if the selection moved to it or it changed.

        :param idx: Row index in the list control.
        :param moved: True when the selection has just moved to this row.
        """
        keys = list(self.listitems.keys())
        if idx < 0 or idx >= len(keys):
            return
        runtime_id = keys[idx]
        li = self._list_container.getListItem(idx)
        shown = self._rows_shown.setdefault(idx, {})
        changed = self._apply_row_visuals(
            li, self.listitems[runtime_id], runtime_id, shown
        )
        if moved or changed:
            self._ring()

    def _ring(self) -> None:
        """Send the served ring the skin passed (``ring``), if any, in this window."""
        if self.ring:  # its token, a Home property
            LockedCalls.write(ring, self.ring, window=self._window_id)

    def _refresh_ui(self, update_row: bool = True, focus_id: int | None = None) -> None:
        """
        Update all dynamic handlers and bottom description for current slot.

        :param update_row: Flag determining whether the current row's label should be updated.
        :param focus_id: Control with focus when known (onAction's, a queued SetFocus).
        """
        if self.current_listitem is None or self.current_listitem not in self.listitems:
            return

        focus_id = focus_id or self.getFocusId()
        for h in self.handlers.values():
            h.update_value()
        self._draw_handlers(focus_id)
        # A page with nothing to focus: the rail's Right stays put (editor.xml)
        locked = not any(h.focusable for h in self.handlers.values())
        if locked != self._page_locked:
            self._page_locked = locked
            LockedCalls.write(self.setProperty, "page_locked", "true" if locked else "")
        if update_row:
            self._refresh_list_row(self.container_position)

        self._set_description(focus_id)

    def _draw_handlers(self, focus_id: int) -> None:
        """
        Write every handler's labels; when rows show or hide, the labels and then those
        rows back to back inside ``page_turning``, so a skin can hide a page caught
        half changed.

        :param focus_id: Control with focus, for the labels' focused colours.
        """
        flips = [
            (h, visible)
            for h in self.handlers.values()
            if (visible := h.evaluate_visibility()) != h.shown
        ]
        if not flips:
            for h in self.handlers.values():
                h.update_labels(focus_id)
            return
        # Labels and visibility each wait for Python's once-a-frame slot
        # (Application.cpp:1849-1862): the time shows whether the burst straddled a
        # frame. The labels go inside, or a row about to hide shows the new one's
        start = time.perf_counter()
        LockedCalls.write(self.setProperty, "page_turning", "true")
        try:  # a failed label mustn't leave the skin's column hidden
            for h in self.handlers.values():
                h.update_labels(focus_id)
            for h, visible in flips:
                h.write_visibility(visible)
        finally:
            LockedCalls.write(self.setProperty, "page_turning", "")
        log.debug(
            f"{self.__class__.__name__} → page turn: {len(flips)} rows in "
            f"{(time.perf_counter() - start) * 1000:.1f} ms"
        )

    def _set_description(self, focus_id: int) -> None:
        """
        Resolve and set the bottom description for the current focus:
        handler description, else mgmt-button description, else the
        selected listitem's description.

        :param focus_id: GUI control ID that currently has focus.
        """
        handler = (
            self._handler_by_focus_id.get(focus_id)
            if self.current_listitem in self.listitems
            else None
        )
        if handler and handler.description:
            desc = self.runtime_manager.format_metadata(
                handler.mapping_key,
                self._source_index,
                handler.description,
                localize=True,
            )
        else:
            desc = next(
                (
                    entry["description"]
                    for entry in self._mgmt_map.values()
                    if entry["id"] == focus_id
                ),
                "",
            )
        if not desc and self.current_listitem in self.listitems:
            item = self.listitems[self.current_listitem]
            desc = self.runtime_manager.format_metadata(
                item["mapping"],
                self._source_index,
                item.get("description", ""),
                localize=True,
            )
        desc = desc or ""
        if desc != self._description:
            self._description = desc
            self._description_label.setText(desc)

    def _update_mgmt_buttons(self) -> None:
        """Enable/disable mutation buttons based on list position and size."""
        m = self._mgmt_map
        if not self._has_governor:
            return

        has_items = bool(self.listitems)
        n = len(self.listitems)
        for key, enabled in (
            ("btn_delete", n > 1),
            ("btn_up", has_items and self.container_position > 0),
            ("btn_down", has_items and self.container_position < n - 1),
        ):
            # As BaseControlHandler.set_enabled: an unchanged state isn't written
            if m[key].get("enabled") != enabled:
                m[key]["enabled"] = enabled
                LockedCalls.write(m[key]["btn"].setEnabled, enabled)

    def _refresh_handlers_after_mapping_change(self) -> None:
        """
        Re-evaluate all handler values and visibility after a preset change,
        resetting any field values that are no longer valid.
        """
        for h in self.handlers.values():
            h.refresh_after_mapping_item_change()
        self._draw_handlers(self.getFocusId())
        self._refresh_list_row(self.container_position)

    def onAction(self, action: xbmcgui.Action) -> None:
        """
        Called by Kodi when the user performs an action; logs at debug how long the
        action took and how many locked writes it made, each up to a frame's wait.

        :param action: xbmcgui.Action object.
        """
        start = time.perf_counter()
        LockedCalls.count = 0
        self._on_action(action)
        log.debug(
            f"{self.__class__.__name__} → action {action.getId()}: "
            f"{(time.perf_counter() - start) * 1000:.1f} ms, "
            f"{LockedCalls.count} locked writes"
        )

    def _on_action(self, action: xbmcgui.Action) -> None:
        """
        Route an action to the list, a control handler or a management button.

        :param action: xbmcgui.Action object.
        """
        # A mouse click acts as Select: the window has no onClick.
        a_id = action.getId()
        if a_id == ACTION_MOUSE_LEFT_CLICK:
            a_id = ACTION_SELECT_ITEM
        current_focus = self.getFocusId()
        prev_focus = self._prev_focus_id
        if self._page_changed and current_focus in self._handler_by_focus_id:
            self._set_page_changed(False)

        # Exit targets are only recorded by actions on host_focus; seeing
        # one ⇒ close, the exit router performs the window change.
        if (
            self.host
            and str(current_focus) == str(self.host_focus)
            and infolabel("Window(home).Property(host_exit_target)")
        ):
            return self._on_close()

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
            self._on_list_scroll(current_focus)
            return

        # List or handler interactions
        if current_focus == self._list_container.getId():
            if prev_focus != current_focus:
                self._refresh_ui(update_row=False, focus_id=current_focus)
            self._on_list_scroll(current_focus)
        else:
            # Kodi redraws a pressed control itself, whether focus was already there
            # or came with the press (a mouse click)
            if a_id == ACTION_SELECT_ITEM:
                for focus_id in {prev_focus, current_focus}:
                    if pressed := self._handler_by_focus_id.get(focus_id):
                        pressed.pressed()

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

                # Back leaves the row for the list, refreshed for the list below
                if a_id not in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
                    self._draw_handlers(current_focus)

            # Description — always update (mgmt buttons have descriptions too)
            self._set_description(current_focus)

            # Management buttons — Add works on empty lists; up/down/delete need a selection
            if a_id == ACTION_SELECT_ITEM and self._mgmt_buttons:
                entry = next(
                    (e for e in self._mgmt_map.values() if e["id"] == current_focus),
                    None,
                )
                if entry and (not entry["needs_selection"] or has_valid_selection):
                    return entry["action"]()

        if a_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
            # Back on host_focus exits the host's system, not into the editor.
            if self.host_focus and str(current_focus) == str(self.host_focus):
                return self._on_close()
            list_id = self._list_container.getId()
            if current_focus != list_id:
                log.execute(f"Control.SetFocus({list_id})")
                # SetFocus is queued, so getFocusId() still gives the row: name the list
                self._refresh_ui(update_row=False, focus_id=list_id)
                self._prev_focus_id = list_id
                return  # don't fall through to super
            if self.host_focus:  # hosted: the list steps back to the tab strip first
                log.execute(f"Control.SetFocus({self.host_focus})")
                self._prev_focus_id = int(self.host_focus)
                return

            return self._on_close()

        self._prev_focus_id = current_focus
        super().onAction(action)

    def _on_list_scroll(self, focus_id: int) -> None:
        """
        Handle user scrolling in the left list: the row's entry is the one drawn on it,
        and none is left after the window closes on an emptied list with a key queued.

        :param focus_id: Control that has focus, so the refresh needn't ask Kodi.
        """
        idx = self._list_container.getSelectedPosition()
        if idx < 0 or idx == self.container_position:
            return
        content_id = self._rows_shown[idx]["properties"]["content_id"]
        if content_id not in self.listitems:
            return

        self.container_position = idx
        self._update_mgmt_buttons()
        # Rows hide and show one at a time: no flag meanwhile, or a Right finding no
        # row sends FirstPage to the rail.
        self._set_page_changed(False)
        self.current_listitem = content_id
        self._refresh_ui(update_row=False, focus_id=focus_id)
        self._refresh_list_row(idx, moved=True)  # rings once for the move
        self._set_page_changed(True)

    def _set_page_changed(self, changed: bool) -> None:
        """
        Flag a new page for the rail's Right, which then enters the column at its
        first row, scrolled up (editor.xml); the property is written only on a change.

        :param changed: True once a new page's rows are up, False otherwise.
        """
        if changed != self._page_changed:
            self._page_changed = changed
            LockedCalls.write(
                self.setProperty, "page_changed", "true" if changed else ""
            )

    def _begin_mutation(self) -> None:
        """
        Re-sync listitems with on-disk state before any index math. Nested
        editors can mutate other mappings mid-session (delete_orphans), so
        cached runtime_index values may be stale after a bare reload.
        """
        prev_keys = list(self.listitems)
        self.runtime_manager.reload_state()
        self._build_dicts()
        if list(self.listitems) != prev_keys:
            self._refresh_list()
        if self.current_listitem and self.current_listitem in self.listitems:
            self.container_position = list(self.listitems).index(self.current_listitem)
            self._list_container.selectItem(self.container_position)
        else:
            self.current_listitem = None
            self.container_position = min(
                self.container_position, len(self.listitems) - 1
            )

    def _resync_session(self) -> None:
        """
        Adopt on-disk state after an in-process mutation: reload, rebuild, redraw.
        The list always refreshes, as deterministic ids let values change under
        identical keys. Selection survives if its entry still exists, else re-anchors.
        """
        self._begin_mutation()
        self._build_dicts()
        self._refresh_list()
        if self.current_listitem is None and self.listitems:
            self.container_position = 0
            self.current_listitem = next(iter(self.listitems))
        self._finalize_selection(mapping_changed=True, list_rebuilt=True)

    def _on_add(self) -> None:
        """
        Insert a new entry. Runs the governing handler's dialog (item_picker
        or add_action) before inserting, so nothing is written on cancel.
        """
        self._begin_mutation()

        if self.current_listitem:
            mk = self.listitems[self.current_listitem]["mapping"]
        else:
            mk = next(
                (ctrl["mapping"] for ctrl in self.dynamic_controls.values()),
                None,
            )
            if not mk:
                return

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
        if governing is None:
            # Control definitions promised a governor but its XML control
            # failed to attach — abort rather than silently inserting a
            # preset the mapping may not define.
            log.warning("_on_add: no governing handler attached; aborting")
            return

        # Dialog before insert — determines preset and/or field data
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

        # Insert entry
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

        # Apply browse data (add_action only — picker seeds via metadata)
        if browse_result is not None:
            governing.apply_result(browse_result, cfg)

        # Apply picker chained action result (if any)
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
        self._begin_mutation()
        if not self.current_listitem:
            return

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

        self._begin_mutation()
        if not self.current_listitem:
            return

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
        Reset entries to defaults after user confirmation. Scoped to
        parent_filter when set; otherwise resets the whole mapping.
        """
        confirmed = xbmcgui.Dialog().yesno(
            ADDON.getLocalizedString(32833), ADDON.getLocalizedString(32834)
        )
        if not confirmed:
            return

        self._begin_mutation()

        if self.current_listitem and self.current_listitem in self.listitems:
            mk = self.listitems[self.current_listitem]["mapping"]
        else:
            mk = next(
                (ctrl["mapping"] for ctrl in self.dynamic_controls.values()),
                None,
            )
            if not mk:
                return

        if self.parent_filter:
            parent_item = self.runtime_manager.mapping_item_for_runtime_id(
                self.parent_filter
            )
            # Delete descending — each removal shifts later indices left, so
            # ascending deletion with pre-captured indices removes the wrong
            # entries once two or more children exist.
            for item in sorted(
                self.listitems.values(),
                key=lambda i: i["runtime_index"],
                reverse=True,
            ):
                self.runtime_manager.delete_mapping_item(mk, item["runtime_index"])
            for mi in self.runtime_manager.default_children(mk, parent_item):
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
            # Picker path calls _refresh_handlers_after_mapping_change
            # directly, so that method must validate+render as a unit; the
            # extra pass here for _on_add/_on_reset is redundant but cheap.
            self._refresh_handlers_after_mapping_change()

        self._update_mgmt_buttons()
        self._refresh_ui(update_row=not list_rebuilt)
        self._update_mgmt_buttons()

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
            **(
                {"parent": existing[idx]["parent"]} if "parent" in existing[idx] else {}
            ),
        }
        rebuilt = self.runtime_manager.rebuild_mapping_item(
            mk, new_preset, idx, preserve=preserve
        )
        if rebuilt is None:
            log.debug(f"_seed_metadata: rebuild failed for {mk}[{idx}]={new_preset}")
