"""
Offline checks for art details (shared/art_details.py, apis/wikidata.py, the
art_details handler and the art_details_folder / _refresh actions): the file name's
parse; the title words; each of the 25 Nov filename test's 16 files matched or
left empty (title similarity, a label's words all in the title, the year, ties to
the most sitelinks, the threshold); a match's fields; the per-file verdict (kept by
path and mtime, a miss kept too, none kept when Wikidata isn't asked or refuses, a
429 holding the queue); the marked folders; the serve's properties and Home
properties; chips fitted to a row.

Network calls are replaced by answers in the query service's and Wikipedia's shapes,
built from tests/fixtures/wikidata_works.json (hand-written from the filename test's
results: see its note). Run from the helper root:
python tests/art_details_offline.py
"""

import json
import re
import sys
from collections import deque
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import unquote

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
MTIMES = {}  # a file's path → its mtime, for xbmcvfs.Stat


class Monitor:
    """Kodi's Monitor: never exiting, and a wait returns at once."""

    def abortRequested(self):
        return False

    def waitForAbort(self, seconds=0):
        return False


vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Monitor=Monitor,
    getSupportedMedia=lambda media: ".png|.jpg|.jpeg|.gif|.tif|.cbz|.zip|.rss|.webp",
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.modules["xbmcvfs"].mkdirs = lambda path: Path(path).mkdir(exist_ok=True) or 1
sys.modules["xbmcvfs"].Stat = lambda path: SimpleNamespace(
    st_mtime=lambda: MTIMES.get(path, 0)
)
sys.path.insert(0, str(HELPER))

from resources.lib.apis import cache, wikidata  # noqa: E402
from resources.lib.apis.http import HttpError  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.script import actions  # noqa: E402
from resources.lib.shared import art_details as art  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402

FIXTURE = json.loads((HELPER / "tests/fixtures/wikidata_works.json").read_text("utf-8"))
HOME = sys.modules["xbmcgui"].Window(10000)
FOLDER = "/pictures/Art/"
NAMES = {  # the filename test's 16 files: the work each matches, or None
    "Edvard Munch - 'Madonna' (1894-1895).jpg": "Q1989780",
    "Edvard Munch - The 'Scream' (1893).jpg": "Q471379",
    "Franz Marc - 'Blue Horse' (1911).jpg": "Q900010",  # I or II: version unsure
    "Franz Marc - 'Foxes' (1913).jpg": "Q28839414",
    "Franz Marc - 'Horse in a Landscape' (1910).jpg": "Q52086838",
    "Franz Marc - 'In the Rain' (1912).jpg": "Q46159302",
    "Franz Marc - 'Tiger' (1912).jpg": "Q2358487",
    "Katsushika Hokusai - 'Behind the Great Wave at Kanagawa' from Cycle '36 Views "
    "of Mt Fuji' (1823-1829).jpg": "Q252485",
    "Natalia Goncharova - 'Yellow and Green Forest' (1912).jpg": None,
    "Natalia Goncharova - Los Gatos (1913).jpg": None,
    "Vincent Van Gogh - 'Starry Night over The Rhone' (1888).jpg": "Q1464531",
    "Vincent Van Gogh - 'Starry Night' (1890).jpg": "Q45585",
    "Vincent Van Gogh - 'The Olive Trees' (1889).jpg": "Q900040",
    "Wassily Kandinksy - 'Composition Seven' (1913).jpg": "Q2990634",
    "Wassily Kandinksy - 'Moscow' (1916).jpg": "Q3865997",
    "Wassily Kandinsky - 'On White II' (1923).jpg": "Q18705520",
}


def literal(value, lang=None):
    """A query service binding: an entity or an unknown value's node is a uri."""
    kind = "uri" if value.startswith("http://") else "literal"
    return {"type": kind, "value": value} | ({"xml:lang": lang} if lang else {})


def works_rows(search):
    """The works query's rows for a search, as the query service answers them."""
    artist = FIXTURE["artists"].get(search, {})
    if isinstance(artist, str):  # the right spelling finds what the fuzzy one does
        artist = FIXTURE["artists"][artist]
    rows = []
    for qid, links, years, labels in artist.get("works", []):
        row = {
            "artist": literal(wikidata.ENTITY + artist["qid"]),
            "artistLabel": literal(artist["label"], "en"),
            "work": literal(wikidata.ENTITY + qid),
            "links": literal(str(links)),
            "labels": literal(wikidata.SEPARATOR.join(labels)),
        }
        if years:  # a work with no inception has no years binding
            row["years"] = literal(" ".join(map(str, years)))
        rows.append(row)
    return rows


def painting_rows(qid):
    """The painting query's rows: kind, value, the value's label, a material's part."""
    names = "kind", "value", "valueLabel", "part"
    return [
        {name: literal(text) for name, text in zip(names, row)}
        for row in FIXTURE["paintings"].get(qid, [])
    ]


class ArtDetailsTest(unittest.TestCase):
    """Wikidata and Wikipedia answer from the fixture; each request is in self.asked."""

    def setUp(self):
        self.asked, self.refuse = [], None
        ApiCacheHandler().clear("wikidata:%")
        art.FOLDERS.unlink(missing_ok=True)
        HOME.clearProperty(wikidata.NEXT_CALL)
        MTIMES.clear()
        for target, name, value in (
            (wikidata.http, "get_json", self.answer),
            (handlers, "set_items", lambda items, **kwargs: items),
            (handlers.ADDON, "getSettingBool", lambda key: key == "wikidata"),
            (wikidata, "NEXT_CALL", ""),  # no queue: a test asks faster than 1 a second
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def answer(self, url, params=None, headers=None, timeout=5, body=None):
        if self.refuse:
            raise self.refuse
        if url == wikidata.SPARQL:
            query = params["query"]
            if qid := re.search(r"VALUES \?work \{ wd:(Q\d+) \}", query):
                self.asked.append(f"painting {qid[1]}")
                return {"results": {"bindings": painting_rows(qid[1])}}
            search = re.search(r'srsearch "(.+?) haswbstatement', query)[1]
            self.asked.append(f"works {search}")
            return {"results": {"bindings": works_rows(search)}}
        title = unquote(url.removeprefix(wikidata.SUMMARY)).replace("_", " ")
        self.asked.append(f"summary {title}")
        if title not in FIXTURE["summaries"]:
            raise HttpError(404)
        return {"extract": FIXTURE["summaries"][title]}

    def test_parse(self):
        name = art.parse(f"{FOLDER}{next(iter(NAMES))}")
        self.assertEqual(name, ("Edvard Munch", "Madonna", (1894, 1895)))
        hokusai = art.parse([n for n in NAMES if "Hokusai" in n][0])
        self.assertEqual(hokusai.title, "Behind the Great Wave at Kanagawa")
        self.assertEqual(
            art.parse("Munch - The Scream (1893-95).png").years, (1893, 1895)
        )
        self.assertEqual(
            art.parse("Munch - Van Gogh's Chair.jpg").title, "Van Gogh's Chair"
        )
        self.assertEqual(art.parse("smb://nas/Art/Munch - Scream").title, "Scream")
        self.assertIsNone(art.parse("IMG_2041.jpg"))

    def test_words(self):
        self.assertEqual(
            art.words("Starry Night over the Rhône"), ["starry", "night", "rhone"]
        )
        self.assertEqual(art.words("Composition Seven"), art.words("Composition VII"))
        self.assertEqual(art.words("Composition 7"), ["composition", "vii"])

    def test_the_sixteen_files(self):
        for name, qid in NAMES.items():
            with self.subTest(name=name):
                artist = wikidata.works(art.parse(name).artist)
                found = art.match(art.parse(name), artist["works"])
                self.assertEqual(found and found[0], qid)

    def test_fuzzy_artist(self):
        artist = wikidata.works("Wassily Kandinksy")
        self.assertEqual(artist["label"], "Wassily Kandinsky")
        self.assertEqual(
            self.asked, ["works Wassily Kandinksy", "works Wassily~ Kandinksy~"]
        )
        # each search is a request of its own, kept under its own key
        self.assertEqual(
            ApiCacheHandler().get("wikidata:works:wassilykandinksy")[0], {}
        )
        self.assertTrue(ApiCacheHandler().get("wikidata:fuzzy:wassilykandinksy")[0])

    def test_label_words_in_the_title(self):
        hokusai = art.parse([n for n in NAMES if "Hokusai" in n][0])
        labels = ["The Great Wave off Kanagawa"]
        title = art.words(hokusai.title)
        self.assertGreaterEqual(art.title_score(title, labels), art.CONTAIN)
        self.assertLess(art.title_score(title, ["Great Wave"]), art.CONTAIN)  # two

    def test_a_short_label_in_a_long_title_is_no_match(self):
        for name in (  # the 25 Nov review's cases
            "Vincent Van Gogh - 'Self-Portrait with Bandaged Ear and Pipe' (1889).jpg",
            "Natalia Goncharova - 'Yellow and Green Forest' (1912).jpg",
            "Franz Marc - 'Blue Horse with Rainbow' (1913).jpg",
            "Edvard Munch - 'Girls on the Bridge in Moonlight'.jpg",
        ):
            with self.subTest(name=name):
                parsed = art.parse(name)
                works = wikidata.works(parsed.artist)["works"]
                self.assertIsNone(art.match(parsed, works))

    def test_ties_go_to_sitelinks(self):
        name = art.Name("Vincent Van Gogh", "The Starry Night", (1889, 1889))
        works = [
            ["Q2", 3, [1889], ["The Starry Night"]],
            ["Q1", 120, [1889], ["The Starry Night"]],
        ]
        self.assertEqual(art.match(name, works), ("Q1", 1.15))
        self.assertEqual(art.match(name, works[::-1]), ("Q1", 1.15))

    def test_threshold(self):
        name = art.Name("Natalia Goncharova", "Yellow and Green Forest", (1912, 1912))
        works = [["Q1", 3, [1911], ["Rayonism Blue-Green Forest"]]]
        self.assertIsNone(art.match(name, works))
        self.assertEqual(art.year_score((1912, 1912), [1915]), art.YEAR_FAR)
        self.assertEqual(art.year_score((1823, 1829), [1830]), art.YEAR_NEAR)
        self.assertEqual(art.year_score(None, [1830]), 0)

    def test_fields(self):
        path = f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg"
        found = art.look_up(path)
        self.assertEqual(
            {k: found[k] for k in ("title", "artist", "year", "medium", "genre")},
            {
                "title": "The Starry Night",
                "artist": "Vincent van Gogh",
                "year": "1889",
                "medium": "Oil on canvas",
                "genre": "landscape art",
            },
        )
        self.assertEqual(found["collection"], "Museum of Modern Art")
        self.assertEqual(found["dimensions"], "73.7 × 92.1 cm")
        self.assertEqual(found["depicts"], ["star", "Moon", "cypress"])
        self.assertTrue(found["summary"].startswith("The Starry Night is"))
        self.assertEqual((found["qid"], found["artist_qid"]), ("Q45585", "Q5582"))

    def test_private_collection_and_no_article(self):
        path = f"{FOLDER}Vincent Van Gogh - The Bedroom (1888).jpg"
        found = art.look_up(path)
        self.assertIsNone(found["collection"])  # Wikidata's unknown value
        self.assertEqual((found["summary"], found["genre"]), ("", ""))
        self.assertEqual(found["dimensions"], "72 × 90 cm")
        self.assertEqual(found["year"], "1888")  # an unknown inception: the file's
        self.assertEqual(found["medium"], "Oil on canvas")  # canvas, no qualifier
        self.assertEqual(art.verdict(path), found)  # kept, not asked for ever
        props = handlers.PluginHandlers({})._art_properties(found)
        self.assertEqual(props["art_collection"], "Private collection")

    def test_an_unlabelled_collection_is_not_private(self):
        # The Starry Night's first collection has no English label: left out
        found = art.look_up(f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg")
        self.assertEqual(found["collection"], "Museum of Modern Art")
        name = art.Name("Vincent Van Gogh", "The Bedroom", (1888, 1888))
        artist = {"qid": "Q5582", "label": "Vincent van Gogh"}

        def collection(work):
            return art.fields(name, artist, "Q1", work, "")["collection"]

        self.assertEqual(
            collection({"collection": [None, "Musée d'Orsay"]}), "Musée d'Orsay"
        )
        self.assertIsNone(collection({"collection": [None, None]}))  # every one unknown
        self.assertEqual(collection({}), "")  # none at all

    def test_verdict_kept_by_path_and_mtime(self):
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        MTIMES[path] = 100
        self.assertIsNone(art.verdict(path))
        self.assertEqual(art.look_up(path)["qid"], "Q2358487")
        asked = len(self.asked)
        self.assertEqual(art.verdict(path)["qid"], "Q2358487")
        self.assertEqual(len(self.asked), asked)  # from the cache
        MTIMES[path] = 200  # the file changed
        self.assertIsNone(art.verdict(path))

    def test_a_miss_is_kept(self):
        path = f"{FOLDER}Natalia Goncharova - Los Gatos (1913).jpg"
        self.assertEqual(art.look_up(path), {})
        self.assertEqual(art.verdict(path), {})
        self.assertEqual(art.look_up("/pictures/IMG_2041.jpg"), {})  # no artist: no ask
        self.assertEqual(self.asked, ["works Natalia Goncharova"])
        self.assertEqual(art.look_up(f"{FOLDER}Nobody Known - Untitled.jpg"), {})

    def test_no_answer_keeps_no_verdict(self):
        path = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg"
        self.refuse = HttpError(None)  # unreachable
        self.assertIsNone(art.look_up(path))
        self.assertIsNone(art.verdict(path))
        self.refuse, self.asked = None, []
        self.assertIsNone(art.look_up(path))  # within the failure's wait: not asked
        self.assertEqual(self.asked, [])
        ApiCacheHandler().expire("wikidata:%")  # the wait is over
        self.assertEqual(art.look_up(path)["qid"], "Q28839414")

    def test_429_holds_the_queue(self):
        path = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg"
        queue = mock.patch.object(wikidata, "NEXT_CALL", "copacetic.wikidata_next")
        queue.start()
        self.addCleanup(queue.stop)
        self.refuse = HttpError(429, retry_after=60)
        self.assertIsNone(art.look_up(path))
        self.refuse, self.asked = None, []
        self.assertIsNone(art.look_up(f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"))
        self.assertEqual(self.asked, [])  # nothing sent while the wait holds

    def test_refresh(self):
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        art.look_up(path)
        self.asked = []
        actions.art_details_refresh(path)  # the folder isn't marked: nothing sent
        self.assertEqual(self.asked, [])
        art.mark(FOLDER, True)
        with mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: False):
            actions.art_details_refresh(path)  # the setting off: nothing sent
        self.assertEqual(self.asked, [])
        HOME.setProperty("art_details_refresh", path)  # read as written, no decode
        actions.art_details_refresh(prop="art_details_refresh")
        self.assertEqual(self.asked, ["works Franz Marc", "painting Q2358487"])
        self.assertEqual(art.verdict(path)["qid"], "Q2358487")

    def test_forget_drops_its_own_file_only(self):
        mine, other = f"{FOLDER}Tiger_%.jpg", f"{FOLDER}TigerX12.jpg"  # LIKE would
        for path in (mine, other):
            art.look_up(path)  # no " - ": a miss, kept
        art.forget(mine)
        self.assertIsNone(art.verdict(mine))
        self.assertEqual(art.verdict(other), {})

    def test_folders(self):
        self.assertEqual(art.mark("/pictures/Art", True), ["/pictures/Art/"])
        folders = art.mark("smb://nas/Art/", True)
        self.assertTrue(art.covers(folders, "/pictures/Art/Munch/Scream.jpg"))
        self.assertFalse(art.covers(folders, "/pictures/Artists/Scream.jpg"))
        self.assertEqual(art.mark("/pictures/Art/", False), ["smb://nas/Art/"])
        self.assertEqual(art.without_user("smb://ash:pw@nas/Art/"), "smb://nas/Art/")
        self.assertEqual(art.folder("C:\\Art"), "C:\\Art\\")

    def test_folder_action_publishes(self):
        with mock.patch.object(actions, "infolabel", lambda label: "smb://nas/"):
            actions.art_details_folder("smb://ash:pw@nas/Art/", mark="true")
            self.assertEqual(HOME.getProperty("art_details_marked"), "smb://nas/Art/")
            self.assertEqual(HOME.getProperty("art_details_unmarked"), "")
            actions.art_details_folder("smb://nas/Art/")
            # inside an archive the inner URL keeps its password: refused
            actions.art_details_folder("zip://smb%3a%2f%2fash%3apw%40nas/", mark="true")
        self.assertEqual(HOME.getProperty("art_details_unmarked"), "smb://nas/Art/")
        self.assertEqual(art.marked(), [])

    def serve(self, path, params="", again=None):
        query = f"info=art_details{params}&folder={FOLDER}&path={path}"
        plugin = handlers.PluginHandlers(
            dict(p.split("=", 1) for p in query.split("&")), again=again, query=query
        )
        return plugin.art_details()[0]["properties"]

    def test_serve(self):
        path = f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg"
        self.assertEqual(self.serve(path), {})  # an unmarked folder: nothing sent
        self.assertEqual(self.asked, [])
        art.mark(FOLDER, True)
        self.assertEqual(self.serve(path), {})  # a plugin call: kept verdicts only
        self.assertEqual(self.asked, [])
        art.look_up(path)
        props = self.serve(path)
        self.assertEqual(HOME.getProperty("art_details_folder"), FOLDER)
        self.assertEqual(HOME.getProperty("art_details_checked"), FOLDER)
        self.assertEqual(
            [props[f"art_chip{n}"] for n in range(1, 5)],
            [
                "Oil on canvas",
                "landscape art",
                "Museum of Modern Art",
                "73.7 × 92.1 cm",
            ],
        )
        self.assertEqual(props["art_depicts"], "star, Moon, cypress")
        with mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: False):
            self.assertEqual(self.serve(path), {})  # off: nothing

    def asides(self):
        """The aside worker not started; the test drains it by hand."""
        started = []
        thread = lambda target, daemon: mock.Mock(start=lambda: started.append(target))
        patcher = mock.patch.object(cache, "Thread", thread)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(art.ASIDES.asked.clear)
        self.addCleanup(art.ASIDES.queue.clear)
        self.addCleanup(setattr, art.ASIDES, "running", 0)
        return started

    def test_served_looks_up_aside(self):
        started = self.asides()
        art.mark(FOLDER, True)
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        asker = mock.Mock(current=lambda: True)
        self.assertEqual(self.serve(path, again=asker), {})  # none yet: blank
        self.assertEqual(self.asked, [])  # the serve itself sends nothing
        self.assertEqual(len(started), 1)
        art.ASIDES._drain()  # the worker, here
        asker.assert_called_once()
        self.assertEqual(self.serve(path, again=asker)["art_title"], "Tiger")

    def test_aside_skips_what_no_one_wants(self):
        self.asides()
        art.mark(FOLDER, True)
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        gone = mock.Mock(current=lambda: False)
        art.ASIDES.ask(path, gone)
        art.ASIDES._drain()
        self.assertEqual((self.asked, gone.call_count), ([], 0))
        art.mark(FOLDER, False)  # unmarked while it waited: still nothing sent
        waiting = mock.Mock(current=lambda: True)
        art.ASIDES.ask(path, waiting)
        art.ASIDES._drain()
        self.assertEqual((self.asked, waiting.call_count), ([], 0))

    def test_only_pictures_are_looked_up(self):
        self.asides()
        art.mark(FOLDER, True)
        asker = mock.Mock(current=lambda: True)
        for name in ("Franz Marc - Tiger (1912).mkv", "Franz Marc - Tiger (1912).cbz"):
            self.assertEqual(self.serve(f"{FOLDER}{name}", again=asker), {})
        self.assertEqual(art.ASIDES.queue, deque())

    def test_folder_state(self):
        art.mark(f"{FOLDER}Munch/", True)
        self.serve(f"{FOLDER}Munch/")
        self.assertEqual(HOME.getProperty("art_details_marked"), f"{FOLDER}Munch/")
        self.serve(f"{FOLDER}Munch/Prints/")  # under a marked folder: neither item
        self.assertEqual(HOME.getProperty("art_details_marked"), "")
        self.assertEqual(HOME.getProperty("art_details_unmarked"), "")
        self.serve(f"{FOLDER}Marc/")
        self.assertEqual(HOME.getProperty("art_details_unmarked"), f"{FOLDER}Marc/")
        self.assertEqual(HOME.getProperty("art_details_folder"), "")

    def test_chips_fit_the_row(self):
        widths = {"a": 100, "b": 200, "c": 50}
        fit = lambda row: art.fit_chips(["a", "b", "c"], widths.get, row, 12)
        self.assertEqual(fit(374), ["a", "b", "c"])
        self.assertEqual(fit(373), ["a", "b"])  # c fits after a, but not after b
        self.assertEqual(fit(99), [])

    def test_served_chips_and_summary_fitted(self):
        art.mark(FOLDER, True)
        metric = SimpleNamespace(getlength=lambda text: 10.0 * len(text))
        params = (
            "&chip_font=meta&chip_row=500&chip_gap=12&chip_padding=12&chip_max=360"
            "&chip_upper=true&summary_font=description_s&summary_width=700"
            "&summary_lines=2"
        )
        path = f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg"
        art.look_up(path)
        with mock.patch.object(handlers, "skin_metric", lambda name: metric):
            props = self.serve(path, params)
        # 130 + 24 twice and a gap: 320; the collection's 224 would end at 556
        self.assertEqual(
            (props["art_chip1"], props["art_chip2"]), ("Oil on canvas", "landscape art")
        )
        self.assertNotIn("art_chip3", props)
        # two lines of 70 characters: the first sentence, not a cut second
        first = FIXTURE["summaries"]["The Starry Night"].partition(". ")[0]
        self.assertEqual(props["art_summary"], f"{first}.")


if __name__ == "__main__":
    unittest.main(verbosity=1)
