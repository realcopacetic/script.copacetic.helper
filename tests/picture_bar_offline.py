"""
Offline checks for a picture's bar on info=progressbar (shared/helpers.py
ProgressBarManager.calculate with resolution_span): the long edge against the span,
capped at 100; no resolution, no bar; without the param, the usual rules; the served
item carries the picture's resolution and size. Run from the helper root:
python tests/picture_bar_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.path.insert(0, str(HELPER))

from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.shared import helpers  # noqa: E402


class PictureBarTest(unittest.TestCase):
    """Kodi's reads stubbed: the focused item's labels are self.labels."""

    def setUp(self):
        self.labels, self.reads = {}, []

        def read(target, keys):
            self.reads.extend(f"{target}.{key}" for key in keys)
            return {key: self.labels.get(key, "") for key in keys}

        for target, name, value in (
            (helpers, "Window", mock.Mock()),
            (helpers, "get_infolabels", read),
            (helpers, "condition", lambda expression: False),
            (helpers.ProgressBarManager, "update", lambda self, percent, **kw: None),
            (handlers, "set_items", lambda items, **kwargs: items),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fill(self, resolution, span=3840):
        self.labels["PictureResolution"] = resolution
        pb = helpers.ProgressBarManager("Container(58).ListItem", 4010, 10002, 14)
        return pb.calculate(span)

    def test_long_edge_against_the_span(self):
        self.assertEqual(self.fill("1920 x 1520"), (50, ""))
        self.assertEqual(self.fill("1520 x 1920"), (50, ""))  # portrait: its height
        self.assertEqual(self.fill("960 x 540"), (25, ""))
        self.assertIn("Container(58).ListItem.PictureResolution", self.reads)

    def test_capped_at_the_span(self):
        self.assertEqual(self.fill("6000 x 4000"), (100, ""))

    def test_no_resolution_no_bar(self):
        self.assertEqual(self.fill(""), (0, ""))  # tags off, or a file Kodi can't read
        self.assertEqual(self.fill("0 x 0"), (0, ""))

    def test_without_the_param_the_usual_rules(self):
        self.assertEqual(self.fill("1920 x 1520", span=0), (0, ""))
        self.assertNotIn("Container(58).ListItem.PictureResolution", self.reads)

    def serve(self, **params):
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {"target_id": "4010", **params}
        handler.target_item = "Container(58).ListItem"
        handler.dialog, handler.window_id = False, 10002
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        (item,) = handler.progressbar()
        return item

    def test_on_the_progress_item(self):
        self.labels |= {"PictureResolution": "1920 x 1520", "Size": "1.4 MB"}
        item = self.serve(resolution_span="3840")
        self.assertEqual(item["resume"], {"position": 50, "total": 100})
        self.assertEqual(
            item["properties"],
            {
                "unwatchedepisodes": "",
                "plays": "",
                "picture_resolution": "1920 x 1520",
                "picture_size": "1.4 MB",
                "time_left": "",
            },
        )

    def test_size_alone_without_a_resolution(self):
        self.labels["Size"] = "357 KB"
        props = self.serve(resolution_span="3840")["properties"]
        self.assertEqual(
            (props["picture_resolution"], props["picture_size"]), ("", "357 KB")
        )

    def test_no_picture_labels_without_the_param(self):
        self.labels["Size"] = "357 KB"
        self.assertNotIn("picture_size", self.serve()["properties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
