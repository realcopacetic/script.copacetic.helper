"""
Offline checks for the settings editor's runtime edges, with Kodi stubbed: a parent
entry added or switched to an item with default children in a seed_with_parent
mapping gets them once (a group widget's first tab), a reset restores them, and
removing a parent removes its children's children too (a menu item's widgets' tabs);
a new rail page is flagged for the rail's Right only once its rows are up, and
cleared at a row, and a page with no row to focus is locked for it; a mouse click
acts as Select, and a click on a sliderex's slider keeps the value it moved to
before focus flips to the button; Back from a row
refreshes its controls for the list (a sliderex's button loses its focused colours)
when a row is selected, and Back or Previous Menu on an edit row saves what was
typed; a slider step isn't put back by the refresh it triggers, a move not stored is;
a move rings the region the skin opted in to (ring) once, a changed row too, and no
editor without it rings; a row, a radio's state, a management button, an edit's text
and the description aren't written again unchanged (a Select forgets a radio's state,
whether focus was on it or came with the press), an edit shows what it saved,
and entry substitutions are cached until the state changes.
Run from the helper root: python tests/editor_offline.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
(STAGE / "addon.xml").write_text('<addon id="skin.test" />')
MAPPINGS = STAGE / "extras" / "templates" / "mappings"
MAPPINGS.mkdir(parents=True)
(MAPPINGS / "mappings_test.json").write_text(
    json.dumps(
        {
            "menu": {"mode": "dynamic", "items": ["films", "music"]},
            "widgets": {
                "mode": "dynamic",
                "parent_mapping": "menu",
                "items": ["latest", "group"],
                "default_order": [],
                "metadata": {"latest": {"parent": "films"}},
            },
            "tabs": {
                "mode": "dynamic",
                "parent_mapping": "widgets",
                "seed_with_parent": True,
                "items": ["recent", "random", "spare"],
                "default_order": [],
                "metadata": {
                    "recent": {"parent": "group"},
                    "random": {"parent": "group"},
                },
            },
        }
    )
)
xbmcgui = sys.modules["xbmcgui"]
xbmcgui.WindowXMLDialog = type("WindowXMLDialog", (), {"onAction": lambda *_: None})
xbmcgui.Action = object
sys.modules["xbmc"].Monitor = object  # the served transport's, which its rings import
for name, value in {
    "ACTION_MOVE_LEFT": 1,
    "ACTION_MOVE_RIGHT": 2,
    "ACTION_MOVE_UP": 3,
    "ACTION_MOVE_DOWN": 4,
    "ACTION_SELECT_ITEM": 7,
    "ACTION_PREVIOUS_MENU": 10,
    "ACTION_NAV_BACK": 92,
    "ACTION_MOUSE_LEFT_CLICK": 100,
}.items():
    setattr(xbmcgui, name, value)
for name in ("Button", "Edit", "Label", "RadioButton", "Slider"):
    setattr(xbmcgui, f"Control{name}", type(f"Control{name}", (), {}))
sys.path.insert(0, str(HELPER))

from resources.lib.builders.runtime import RuntimeStateManager  # noqa: E402
from resources.lib.windows.controls import (  # noqa: E402
    BaseControlHandler,
    EditHandler,
    RadioButtonHandler,
    SliderExHandler,
    SliderHandler,
)
from resources.lib.windows import dynamiceditor  # noqa: E402
from resources.lib.windows.dynamiceditor import DynamicEditor  # noqa: E402


def rows(manager: RuntimeStateManager, key: str, parent: str) -> list[str]:
    """Items of ``key``'s rows under ``parent``, in state order."""
    return [
        e["mapping_item"]
        for e in manager.runtime_state.get(key, [])
        if e.get("parent") == parent
    ]


class SeededChildren(unittest.TestCase):
    def setUp(self):
        self.manager = RuntimeStateManager.from_templates()
        self.manager.initialize_runtime_state()
        self.menu = self.manager.runtime_state["menu"][0]["runtime_id"]

    def tearDown(self):
        for key in ("menu", "widgets", "tabs"):
            self.manager.runtime_state.pop(key, None)
        self.manager._write_and_invalidate(self.manager.runtime_state)

    def add(self, key: str, item: str, parent: str | None = None) -> str:
        """Insert ``item`` into ``key`` under ``parent``; its runtime_id."""
        extra = {"parent": parent} if parent else None
        return self.manager.insert_mapping_item(key, item, extra_fields=extra)[
            "runtime_id"
        ]

    def switch(self, runtime_id: str, item: str) -> None:
        """Re-preset the widget ``runtime_id`` to ``item``, as the editor's picker."""
        state = self.manager.runtime_state["widgets"]
        index = next(i for i, e in enumerate(state) if e["runtime_id"] == runtime_id)
        preserve = {"runtime_id": runtime_id, "parent": self.menu}
        self.manager.rebuild_mapping_item("widgets", item, index, preserve)

    def test_default_children_in_order(self):
        self.assertEqual(
            self.manager.default_children("tabs", "group"), ["recent", "random"]
        )
        self.assertEqual(self.manager.default_children("tabs", "latest"), [])

    def test_a_new_group_gets_its_tabs(self):
        group = self.add("widgets", "group", self.menu)
        self.assertEqual(rows(self.manager, "tabs", group), ["recent", "random"])

    def test_another_widget_gets_none(self):
        self.add("widgets", "latest", self.menu)
        self.assertEqual(self.manager.runtime_state["tabs"], [])

    def test_a_switch_to_group_seeds_once(self):
        widget = self.add("widgets", "latest", self.menu)
        self.switch(widget, "group")
        self.switch(widget, "latest")
        self.switch(widget, "group")
        self.assertEqual(rows(self.manager, "tabs", widget), ["recent", "random"])

    def test_substitutions_are_cached_until_the_state_changes(self):
        first = self.manager.entry_substitutions("menu", 0)
        self.assertIs(self.manager.entry_substitutions("menu", 0), first)
        self.assertIsNot(
            self.manager.entry_substitutions("menu", 0, include_metadata=True), first
        )
        self.manager.reload_state()
        again = self.manager.entry_substitutions("menu", 0)
        self.assertIsNot(again, first)
        self.assertEqual(again, first)
        self.add("menu", "music")
        self.assertIsNot(self.manager.entry_substitutions("menu", 0), again)

    def test_a_menu_item_seeds_no_widgets(self):
        self.add("menu", "films")
        self.assertEqual(self.manager.runtime_state["widgets"], [])

    def test_a_removed_menu_item_takes_its_widgets_tabs(self):
        group = self.add("widgets", "group", self.menu)
        other = self.add("menu", "music")
        kept = self.add("widgets", "group", other)
        self.manager.delete_mapping_item("menu", 0)
        self.assertEqual(self.manager.delete_orphans("widgets"), 3)
        self.assertEqual(rows(self.manager, "tabs", group), [])
        self.assertEqual(rows(self.manager, "tabs", kept), ["recent", "random"])


def drawn(*content_ids: str) -> dict:
    """``_rows_shown`` for rows drawn with these entries' ids, in order."""
    return {i: {"properties": {"content_id": c}} for i, c in enumerate(content_ids)}


def editor(**attrs) -> DynamicEditor:
    """A DynamicEditor with no window: its property writes recorded in ``props``."""
    ed = DynamicEditor.__new__(DynamicEditor)
    ed.props = {}
    ed.setProperty = ed.props.__setitem__
    ed._page_changed = ed._page_locked = False
    ed.__dict__.update(attrs)
    return ed


class PageChanged(unittest.TestCase):
    def scrolled(self) -> tuple[DynamicEditor, list]:
        """Scroll the rail to its second row; the flag each refresh saw."""
        seen = []
        ed = editor(
            container_position=0,
            listitems={"a": {}, "b": {}},
            _rows_shown=drawn("a", "b"),
            _list_container=Mock(**{"getSelectedPosition.return_value": 1}),
            _update_mgmt_buttons=Mock(),
            _refresh_ui=lambda **_: seen.append(ed.props.get("page_changed")),
            _refresh_list_row=Mock(),
        )
        ed._on_list_scroll(100)
        return ed, seen

    def test_flagged_after_the_rows_are_up(self):
        ed, seen = self.scrolled()
        self.assertEqual(ed.current_listitem, "b")
        self.assertEqual(seen, [None])
        self.assertEqual(ed.props["page_changed"], "true")

    def test_cleared_while_the_rows_change(self):
        ed, seen = self.scrolled()
        ed.container_position = 0
        ed._on_list_scroll(100)
        self.assertEqual(seen, [None, ""])
        self.assertEqual(ed.props["page_changed"], "true")

    def test_a_key_queued_past_an_emptied_list_does_nothing(self):
        ed = editor(
            container_position=0,
            listitems={},
            _rows_shown=drawn("a", "b"),
            _list_container=Mock(**{"getSelectedPosition.return_value": 1}),
            _update_mgmt_buttons=Mock(),
            _refresh_ui=Mock(),
        )
        ed._on_list_scroll(100)
        self.assertEqual(ed.container_position, 0)
        ed._update_mgmt_buttons.assert_not_called()
        ed._refresh_ui.assert_not_called()


class Ring(unittest.TestCase):
    def rings(self, ring: str | None, changed: bool, moved: bool) -> list:
        """The regions a redraw of a row rings."""
        ed = editor(
            ring=ring,
            listitems={"a": {}},
            _rows_shown={},
            _list_container=Mock(),
            _apply_row_visuals=Mock(return_value=changed),
        )
        with patch.object(dynamiceditor, "ring_move") as ring_move:
            ed._refresh_list_row(0, moved=moved)
        return [c.args[0] for c in ring_move.call_args_list]

    def test_a_move_rings_once(self):
        self.assertEqual(self.rings("preview", changed=True, moved=True), ["preview"])
        self.assertEqual(self.rings("preview", changed=False, moved=True), ["preview"])

    def test_a_changed_row_rings(self):
        self.assertEqual(self.rings("preview", changed=True, moved=False), ["preview"])

    def test_an_unchanged_row_stays_quiet(self):
        self.assertEqual(self.rings("preview", changed=False, moved=False), [])

    def test_an_editor_without_the_param_never_rings(self):
        self.assertEqual(self.rings(None, changed=True, moved=True), [])

    def test_a_move_rings_through_the_row(self):
        ed = editor(
            ring="preview",
            container_position=0,
            listitems={"a": {}, "b": {}},
            _rows_shown=drawn("a", "b"),
            _list_container=Mock(**{"getSelectedPosition.return_value": 1}),
            _update_mgmt_buttons=Mock(),
            _refresh_ui=Mock(),
            _refresh_list_row=Mock(),
        )
        ed._on_list_scroll(100)
        ed._refresh_ui.assert_called_once_with(update_row=False, focus_id=100)
        ed._refresh_list_row.assert_called_once_with(1, moved=True)


class Unchanged(unittest.TestCase):
    """A write waits for Kodi's frame slot: one that changes nothing isn't made."""

    def row(self, **entry) -> tuple[DynamicEditor, Mock]:
        """An editor whose row resolves ``entry``, and a list item to draw it on."""
        manager = Mock(
            format_metadata=lambda mk, idx, text, localize: text.upper(),
            resolved_entry=lambda mk, idx: entry,
        )
        return editor(runtime_manager=manager), Mock()

    def test_a_row_writes_only_what_changed(self):
        ed, li = self.row(layout="list", art="poster", count=3)
        item, shown = {"mapping": "m", "runtime_index": 0, "label": "a"}, {}
        self.assertTrue(ed._apply_row_visuals(li, item, "id", shown))
        li.setLabel.assert_called_once_with("A")
        li.setArt.assert_not_called()  # no icon template: the art is left alone
        self.assertEqual(
            [c.args for c in li.setProperty.call_args_list],
            [("content_id", "id"), ("layout", "list"), ("art", "poster")],
        )
        li.reset_mock()
        self.assertFalse(ed._apply_row_visuals(li, item, "id", shown))
        self.assertEqual(li.method_calls, [])
        ed.runtime_manager.resolved_entry = lambda mk, idx: {
            "layout": "reel",
            "art": "poster",
        }
        self.assertTrue(ed._apply_row_visuals(li, {**item, "icon": "i"}, "id", shown))
        li.setProperty.assert_called_once_with("layout", "reel")
        li.setArt.assert_called_once_with({"icon": "I"})
        li.setLabel.assert_not_called()

    def test_a_new_list_draws_every_row_afresh(self):
        container = Mock()
        ed = editor(
            ring=None,
            listitems={"a": {}, "b": {}},
            _rows_shown={0: {"label": "stale"}},
            _list_container=container,
            _apply_row_visuals=Mock(),
        )
        ed._refresh_list()
        self.assertEqual(
            [c.args[3] for c in ed._apply_row_visuals.call_args_list], [{}, {}]
        )
        self.assertEqual(container.addItem.call_count, 2)

    def test_management_buttons(self):
        buttons = {k: Mock() for k in ("btn_delete", "btn_up", "btn_down")}
        ed = editor(
            _has_governor=True,
            listitems={"a": {}, "b": {}, "c": {}},
            container_position=0,
            _mgmt_map={k: {"btn": b} for k, b in buttons.items()},
        )
        ed._update_mgmt_buttons()
        ed._update_mgmt_buttons()
        ed.container_position = 1
        ed._update_mgmt_buttons()
        self.assertEqual(
            {
                k: [c.args[0] for c in b.setEnabled.call_args_list]
                for k, b in buttons.items()
            },
            {"btn_delete": [True], "btn_up": [False, True], "btn_down": [True]},
        )

    def test_description(self):
        label = Mock()
        ed = editor(
            _description=None,
            _description_label=label,
            _handler_by_focus_id={},
            _mgmt_map={"btn_close": {"id": 415, "description": "Close"}},
            current_listitem=None,
            listitems={},
        )
        for focus in (415, 415, 100, 100):
            ed._set_description(focus)
        self.assertEqual(
            [c.args for c in label.setText.call_args_list], [("Close",), ("",)]
        )

    def radio(self, stored: list) -> RadioButtonHandler:
        """A radio over ``stored``'s one value, its first item on."""
        handler = RadioButtonHandler.__new__(RadioButtonHandler)
        handler.instance = Mock(**{"getId.return_value": 300})
        handler._selected, handler._enabled_by_id = None, {}
        handler._allowed_items = lambda: ["true", "false"]
        handler._coerce_to_allowed = lambda: stored[0]
        return handler

    def test_a_radio_writes_a_change_and_after_a_press(self):
        stored = ["true"]
        handler = self.radio(stored)
        handler.update_value()
        handler.update_value()
        stored[0] = "false"
        handler.update_value()
        # Kodi flips the drawn state on the press: a cancelled confirm sets it back
        handler.pressed()
        handler.update_value()
        handler.update_value()
        self.assertEqual(
            [c.args for c in handler.instance.setSelected.call_args_list],
            [(True,), (False,), (False,)],
        )

    def pressed(self, a_id: int) -> tuple[Mock, RadioButtonHandler]:
        """
        An action from a control at 211 that leaves focus on a radio at 300 (a
        click): the 211 handler, and the radio.
        """
        before = Mock(focus_target_id=None)
        radio = self.radio(["true"])
        radio._selected = True
        radio.update_visibility = Mock()
        ed = editor(
            host=None,
            host_focus=None,
            _prev_focus_id=211,
            _mgmt_ids=set(),
            _mgmt_buttons=[],
            _handler_by_focus_id={211: before, 300: radio},
            handlers={"before": before, "radio": radio},
            current_listitem="a",
            listitems={"a": {}},
            _list_container=Mock(**{"getId.return_value": 100}),
            getFocusId=lambda: 300,
            _set_description=Mock(),
        )
        ed.onAction(Mock(**{"getId.return_value": a_id}))
        return before, radio

    def test_a_select_forgets_both_controls_drawn_state(self):
        before, radio = self.pressed(xbmcgui.ACTION_MOUSE_LEFT_CLICK)
        before.pressed.assert_called_once_with()
        self.assertIsNone(radio._selected)

    def test_a_move_keeps_it(self):
        before, radio = self.pressed(xbmcgui.ACTION_MOVE_DOWN)
        before.pressed.assert_not_called()
        self.assertTrue(radio._selected)

    def test_an_edit_shows_what_it_saved(self):
        for typed, cached, shown in (
            ("typed ", "stored", [("typed",)]),
            ("same ", "same", [("same",)]),  # unchanged, nothing saved, still trimmed
            ("same", "same", []),
        ):
            handler = EditHandler.__new__(EditHandler)
            handler.control, handler._cached_text = {}, cached
            handler.instance = Mock(**{"getText.return_value": typed})
            handler._set_setting_value, handler.parent = Mock(), Mock()
            handler._on_interact(300, xbmcgui.ACTION_MOVE_UP)
            self.assertEqual(
                [c.args for c in handler.instance.setText.call_args_list], shown
            )

    def test_an_edit_writes_what_it_doesnt_show(self):
        stored = ["films"]
        handler = EditHandler.__new__(EditHandler)
        handler.field, handler._cached_text = "label", ""
        handler.instance = Mock()
        handler._get_setting_value = lambda: stored[0]
        handler.runtime_manager = Mock(
            literal=lambda text: text,
            format_metadata=lambda mk, idx, text, localize: text,
        )
        handler.mapping_key, handler.parent = "m", Mock(_source_index=0)
        handler.update_value()
        handler.update_value()
        handler._cached_text = ""  # cleared and saved, so its fallback shows next
        handler.update_value()
        self.assertEqual(
            [c.args for c in handler.instance.setText.call_args_list],
            [("films",), ("films",)],
        )


class PageLocked(unittest.TestCase):
    def row(self, control_type: str, shown: bool, enabled: bool) -> BaseControlHandler:
        """A row as update_visibility and set_enabled leave it."""
        handler = BaseControlHandler.__new__(BaseControlHandler)
        handler.control = {"control_type": control_type}
        handler.instance = Mock(**{"getId.return_value": 300})
        handler._shown, handler._enabled_by_id = shown, {300: enabled}
        handler.update_value = handler.update_visibility = Mock()
        return handler

    def refreshed(self, *handlers: BaseControlHandler) -> dict:
        """The window properties a refresh of a page of ``handlers`` writes."""
        ed = editor(
            current_listitem="a",
            listitems={"a": {}},
            handlers=dict(enumerate(handlers)),
            getFocusId=lambda: 100,
            _set_description=Mock(),
        )
        ed._refresh_ui(update_row=False)
        return ed.props

    def test_nothing_to_focus_locks_the_page(self):
        for row in (
            self.row("cycle", True, False),
            self.row("cycle", False, True),
            self.row("label", True, True),
        ):
            self.assertEqual(self.refreshed(row), {"page_locked": "true"})

    def test_one_focusable_row_leaves_it_open(self):
        rows = self.row("label", True, True), self.row("cycle", True, True)
        self.assertEqual(self.refreshed(*rows), {})


class Clicks(unittest.TestCase):
    def test_a_click_presses_a_button(self):
        close = Mock()
        ed = editor(
            host=None,
            _prev_focus_id=415,
            _mgmt_ids=set(),
            _mgmt_buttons=[Mock()],
            _mgmt_map={
                "btn_close": {"id": 415, "action": close, "needs_selection": False}
            },
            _handler_by_focus_id={},
            handlers={},
            current_listitem=None,
            listitems={},
            _list_container=Mock(**{"getId.return_value": 100}),
            getFocusId=lambda: 415,
            _set_description=Mock(),
        )
        ed.onAction(Mock(**{"getId.return_value": 100}))
        close.assert_called_once()

    def test_a_slider_click_keeps_its_value(self):
        slider = Mock(**{"getId.return_value": 211, "getInt.return_value": 1})
        button = Mock(**{"getId.return_value": 2110})
        handler = SliderExHandler.__new__(SliderExHandler)
        handler.instance, handler.button_instance, handler.button_id = (
            slider,
            button,
            2110,
        )
        handler.parent = Mock()
        handler._allowed_items = lambda: ["off", "on"]
        handler._set_setting_value = Mock()
        handler._on_interact(211, xbmcgui.ACTION_SELECT_ITEM)
        handler._set_setting_value.assert_called_once_with("on")
        self.assertEqual(handler.focus_target_id, 2110)


class Back(unittest.TestCase):
    def test_back_from_a_slider_unfocuses_its_button(self):
        handler = Mock(focus_target_id=None)
        ed = editor(
            host=None,
            host_focus=None,
            _prev_focus_id=211,
            _mgmt_ids=set(),
            _mgmt_buttons=[],
            _handler_by_focus_id={211: handler},
            handlers={"slider": handler},
            current_listitem="a",
            listitems={"a": {}},
            _list_container=Mock(**{"getId.return_value": 100}),
            getFocusId=lambda: 211,
            _set_description=Mock(),
        )
        ed.onAction(Mock(**{"getId.return_value": xbmcgui.ACTION_NAV_BACK}))
        handler.update_value.assert_called_once_with()
        handler.update_visibility.assert_called_once_with(100)
        ed._set_description.assert_called_with(100)
        self.assertEqual(ed._prev_focus_id, 100)

    def test_back_without_a_selection_leaves_the_handlers(self):
        handler = Mock(focus_target_id=None)
        ed = editor(
            host=None,
            host_focus=None,
            _prev_focus_id=211,
            _mgmt_ids=set(),
            _mgmt_buttons=[],
            _handler_by_focus_id={211: handler},
            handlers={"slider": handler},
            current_listitem=None,
            listitems={"a": {}},
            _list_container=Mock(**{"getId.return_value": 100}),
            getFocusId=lambda: 211,
            _set_description=Mock(),
        )
        ed.onAction(Mock(**{"getId.return_value": xbmcgui.ACTION_NAV_BACK}))
        handler.update_value.assert_not_called()
        handler.update_visibility.assert_not_called()
        self.assertEqual(ed._prev_focus_id, 100)

    def test_back_or_previous_menu_saves_typed_text(self):
        for a_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            handler = EditHandler.__new__(EditHandler)
            handler.control, handler.is_dynamic_linked = {"control_type": "edit"}, False
            handler._shown, handler._enabled_by_id = True, {}
            handler.focus_target_id = None
            handler.instance = Mock(**{"getId.return_value": 300})
            handler.instance.getText.return_value = "typed "
            handler._cached_text = "stored"
            handler._set_setting_value = Mock()
            handler.update_value, handler.update_visibility = Mock(), Mock()
            ed = editor(
                host=None,
                host_focus=None,
                _prev_focus_id=300,
                _mgmt_ids=set(),
                _mgmt_buttons=[],
                _handler_by_focus_id={300: handler},
                handlers={"edit": handler},
                current_listitem="a",
                listitems={"a": {}},
                container_position=0,
                _list_container=Mock(**{"getId.return_value": 100}),
                getFocusId=lambda: 300,
                _set_description=Mock(),
                _build_dicts=Mock(),
                _refresh_list_row=Mock(),
            )
            handler.parent = ed
            ed.onAction(Mock(**{"getId.return_value": a_id}))
            handler._set_setting_value.assert_called_once_with("typed")
            # Shown again as stored: a cleared row gets its metadata fallback back
            handler.update_value.assert_called_once_with()


class HeldSlider(unittest.TestCase):
    def test_a_step_is_not_put_back_but_an_unstored_move_is(self):
        stored = ["a"]
        slider = Mock(**{"getId.return_value": 211, "getInt.return_value": 1})
        handler = SliderHandler.__new__(SliderHandler)
        handler.instance, handler._enabled_by_id = slider, {}
        handler._stepping = False
        handler._allowed_items = lambda: ["a", "b", "c"]
        handler._active_link = lambda: {"linked_config": "steps"}
        handler._coerce_to_allowed = lambda: stored[0]
        handler._set_setting_value = lambda value: stored.__setitem__(0, value)
        handler.parent = Mock(_refresh_ui=handler.update_value)
        handler._on_interact(211, xbmcgui.ACTION_MOVE_RIGHT)
        self.assertEqual(stored, ["b"])
        slider.setInt.assert_not_called()
        # A wheel or drag Kodi applied without a stored step: the next refresh resets it
        slider.getInt.return_value = 2
        handler.update_value()
        slider.setInt.assert_called_once_with(1, 0, 1, 2)


if __name__ == "__main__":
    unittest.main()
