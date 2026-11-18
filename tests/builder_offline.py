"""
Offline checks for the builders' loop passes (resources/lib/builders/modules.py): an
item's ``also`` metadata gives a pass more per row, its fields over the item's, so
one settings entry feeds a second window's names: static and dynamic mappings,
expressions (append, assign, the inverted fallback) and variables; an item without
it keeps its one pass.
Run from the helper root: python tests/builder_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.path.insert(0, str(HELPER))

from resources.lib.builders.modules import (  # noqa: E402
    ExpressionsBuilder,
    VariablesBuilder,
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


if __name__ == "__main__":
    unittest.main()
