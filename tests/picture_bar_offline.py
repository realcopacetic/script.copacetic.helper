"""
Offline checks for a picture's bar on info=progressbar (shared/helpers.py
ProgressBarManager.calculate with resolution_span): the long edge against the span,
capped at 100; no resolution, no bar; without the param, the usual rules. Run from the
helper root:
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

LABELS = {
    "DBID": "",
    "DBType": "",
    "PercentPlayed": "",
    "PlayCount": "",
    "Property(WatchedEpisodePercent)": "",
    "Property(WatchedProgress)": "",
    "Property(UnwatchedEpisodes)": "",
}


class PictureBarTest(unittest.TestCase):
    """Kodi's reads stubbed: the picture's PictureResolution is self.resolution."""

    def setUp(self):
        self.resolution, self.reads = "", []

        def read(label):
            self.reads.append(label)
            return self.resolution

        for target, name, value in (
            (helpers, "Window", mock.Mock()),
            (helpers, "get_infolabels", lambda target, keys: dict(LABELS)),
            (helpers, "infolabel", read),
            (helpers, "condition", lambda expression: False),
            (helpers.ProgressBarManager, "update", lambda self, percent, **kw: None),
            (handlers, "set_items", lambda items, **kwargs: items),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fill(self, resolution, span=3840):
        self.resolution = resolution
        pb = helpers.ProgressBarManager("Container(58).ListItem", 4010, 10002, 14)
        return pb.calculate(span)

    def test_long_edge_against_the_span(self):
        self.assertEqual(self.fill("1920 x 1520"), (50, ""))
        self.assertEqual(self.fill("1520 x 1920"), (50, ""))  # portrait: its height
        self.assertEqual(self.fill("960 x 540"), (25, ""))
        self.assertEqual(self.reads, ["Container(58).ListItem.PictureResolution"] * 3)

    def test_capped_at_the_span(self):
        self.assertEqual(self.fill("6000 x 4000"), (100, ""))

    def test_no_resolution_no_bar(self):
        self.assertEqual(self.fill(""), (0, ""))  # tags off, or a file Kodi can't read
        self.assertEqual(self.fill("0 x 0"), (0, ""))

    def test_without_the_param_the_usual_rules(self):
        self.assertEqual(self.fill("1920 x 1520", span=0), (0, ""))
        self.assertEqual(self.reads, [])

    def test_on_the_progress_item(self):
        self.resolution = "1920 x 1520"
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {"target_id": "4010", "resolution_span": "3840"}
        handler.target_item = "Container(58).ListItem"
        handler.dialog, handler.window_id = False, 10002
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        (item,) = handler.progressbar()
        self.assertEqual(item["resume"], {"position": 50, "total": 100})
        self.assertEqual(
            item["properties"],
            {"unwatchedepisodes": "", "plays": "", "time_left": ""},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
