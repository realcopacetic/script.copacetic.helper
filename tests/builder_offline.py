"""
Offline checks for the builders' loop passes (resources/lib/builders/modules.py): an
item's ``also`` metadata gives a pass more per row, its fields over the item's, so
one settings entry feeds a second window's names: static and dynamic mappings,
expressions (append, assign, the inverted fallback) and variables; an item without
it keeps its one pass. And for a skin mirror (builders/runtime.py): a new mirrored
field's config default reaches its skin setting when the runtime state is checked,
on a fresh state and on a saved row that never held the field; a saved value wins.
A rendered condition loses every identity true, a run of them closing it too.
Run from the helper root: python tests/builder_offline.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
(STAGE / "addon.xml").write_text('<addon id="skin.test" />')
sys.path.insert(0, str(HELPER))

from resources.lib.builders import runtime  # noqa: E402
from resources.lib.builders.modules import (  # noqa: E402
    ExpressionsBuilder,
    VariablesBuilder,
    elide_true,
)

AKL = "String.StartsWith(Container.FolderPath,plugin://plugin.program.akl)"
TYPES = {
    "mode": "dynamic",
    "items": ["program_addons", "games"],
    "placeholders": {"key": "content_type"},
    "metadata": {
        "program_addons": {"window": "programs", "match": "Container.Content(addons)"},
        "games": {
            "window": "games",
            "match": "String.StartsWith(Container.FolderPath,plugin://)",
            "also": [{"window": "programs", "match": AKL}],
        },
    },
}
ROWS = [
    {"mapping_item": "program_addons", "layout": "list"},
    {"mapping_item": "games", "layout": "grid"},
]
VISIBLE = {
    "items": ["list", "grid"],
    "rules": [
        {"condition": "equals({layout}, {item})", "type": "append", "value": "{match}"}
    ],
    "fallback_key": "window",
    "fallbacks": {"*": {"target_item": "list", "value": "invert()"}},
}
INCLUDE = {
    "items": ["list", "grid"],
    "rules": [
        {"condition": "equals({layout}, {item})", "type": "assign", "value": "true"}
    ],
}


class State:
    """The runtime manager's two reads, over ROWS."""

    def live_rows(self, mapping):
        return list(enumerate(ROWS))

    def resolved_entry(self, mapping, index):
        return ROWS[index]


def built(builder, mapping, name, template):
    """One template's output, by name."""
    made = builder("content_types", mapping, State(), registry={})
    return {k: v for d in made.process_elements(name, template) for k, v in d.items()}


class Also(unittest.TestCase):
    def test_entry_feeds_both_windows(self):
        visible = built(
            ExpressionsBuilder, TYPES, "layout_{item}_visible_{window}", VISIBLE
        )
        self.assertEqual(
            visible,
            {
                "layout_list_visible_programs": f"![{AKL}]",
                "layout_grid_visible_programs": AKL,
                "layout_list_visible_games": f"![{TYPES['metadata']['games']['match']}]",
                "layout_grid_visible_games": TYPES["metadata"]["games"]["match"],
            },
        )

    def test_assign_fires_for_the_second_window(self):
        include = built(
            ExpressionsBuilder, TYPES, "layout_{item}_include_{window}", INCLUDE
        )
        self.assertEqual(include["layout_grid_include_programs"], "true")
        self.assertEqual(include["layout_grid_include_games"], "true")
        self.assertEqual(include["layout_list_include_games"], "false")

    def test_variable_gains_a_row_with_the_entrys_index(self):
        template = {
            "index": {"start": 1},
            "values": [
                {
                    "condition": "Window.Is({window}) + {match}",
                    "value": "{content_type} {index}",
                }
            ],
        }
        rows = built(VariablesBuilder, TYPES, "focus_item", template)["focus_item"]
        self.assertEqual(
            [(row["condition"].split(" + ")[0], row["value"]) for row in rows],
            [
                ("Window.Is(programs)", "program_addons 1"),
                ("Window.Is(games)", "games 2"),
                ("Window.Is(programs)", "games 2"),
            ],
        )

    def test_static_mapping(self):
        mapping = TYPES | {"mode": "static"}
        template = {"rules": [{"type": "append", "value": "{match}"}]}
        seen = built(ExpressionsBuilder, mapping, "seen_{window}", template)
        self.assertEqual(
            seen,
            {
                "seen_programs": f"Container.Content(addons) | {AKL}",
                "seen_games": TYPES["metadata"]["games"]["match"],
            },
        )

    def test_item_without_it_has_one_pass(self):
        metadata = {
            item: {k: v for k, v in fields.items() if k != "also"}
            for item, fields in TYPES["metadata"].items()
        }
        visible = built(
            ExpressionsBuilder,
            TYPES | {"metadata": metadata},
            "layout_{item}_visible_{window}",
            VISIBLE,
        )
        self.assertEqual(visible["layout_grid_visible_programs"], "false")
        self.assertEqual(visible["layout_list_visible_programs"], "true")


class MirrorDefault(unittest.TestCase):
    """A radiobutton added to a settings category, on by default, mirrored."""

    FIELD = "controller_diagrams"
    MAPPINGS = {
        "copacetic": {
            "mode": "dynamic",
            "items": ["views"],
            "placeholders": {"key": "settings_category"},
            "skin_mirrors": {FIELD: FIELD},
            "config_fields": {"views": {FIELD: FIELD}},
        }
    }
    CONFIGS = {
        "copacetic": {
            FIELD: {"items": {"true": "On", "false": "Off"}, "defaults": {"*": "true"}}
        }
    }

    def check(self, saved=None, skin_has=False):
        """Check the runtime state over a saved one; the builtins it ran."""
        state = Path(tempfile.mkdtemp(dir=STAGE), "runtime_state.json")
        if saved is not None:
            state.write_text(json.dumps({"copacetic": saved}))
        manager = runtime.RuntimeStateManager(
            self.MAPPINGS, self.CONFIGS, {}, str(state)
        )
        ran, on = [], f"Skin.SetBool({self.FIELD})"

        def builtin(action):  # the skin setting follows, as Kodi's does
            nonlocal skin_has
            ran.append(action)
            skin_has = action == on

        with (
            patch.object(runtime, "condition", lambda text: skin_has),
            patch.object(runtime, "executebuiltin", builtin),
        ):
            manager.initialize_runtime_state()
        return ran

    def test_fresh_state(self):
        self.assertEqual(self.check(), [f"Skin.SetBool({self.FIELD})"])

    def test_saved_row_without_the_field(self):
        row = {"runtime_id": "1", "mapping_item": "views", "channel_logos": "true"}
        self.assertEqual(self.check([row]), [f"Skin.SetBool({self.FIELD})"])
        self.assertEqual(self.check([row], skin_has=True), [])  # already on

    def test_saved_off_wins(self):
        row = {"runtime_id": "1", "mapping_item": "views", self.FIELD: "false"}
        self.assertEqual(self.check([row]), [])
        self.assertEqual(
            self.check([row], skin_has=True), [f"Skin.Reset({self.FIELD})"]
        )


class ElideTrue(unittest.TestCase):
    def test_every_identity_true_goes(self):
        self.assertEqual(elide_true("a + true + true"), "a")
        self.assertEqual(elide_true("true + true + a + true"), "a")
        self.assertEqual(elide_true("[true + b] | a + true + c"), "[b] | a + c")
        self.assertEqual(elide_true("true + true"), "")
        self.assertEqual(elide_true("!true + a"), "!true + a")  # not an identity


if __name__ == "__main__":
    unittest.main()
