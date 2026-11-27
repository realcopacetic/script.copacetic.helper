"""
Offline checks for art details (shared/art_details.py, apis/wikidata.py, the
art_details handler and the art_details_folder / _refresh actions): the file name's
parse; the title words; each of the 25 Nov filename test's 16 files matched or
left empty (title similarity, a label's words all in the title, the year, ties to
the most sitelinks, the threshold); a match's fields; the per-file verdict (kept by
path and mtime, a miss kept too, none kept when Wikidata isn't asked or refuses, a
429 holding the queue); the marked folders; the serve's properties and Home
properties; chips fitted to a row. The artist page (art_artist, art_rail and the
art_artist action): its fields, kept answers served and stale ones asked aside, the
setting tested before each request, the rails, and the Back history. The search
(art_search): kept verdicts in marked folders, ranked, with no request.

Network calls are replaced by answers in the query service's and Wikipedia's shapes,
built from tests/fixtures/wikidata_works.json and wikidata_artist.json (hand-written:
see their notes). Run from the helper root:
python tests/art_details_offline.py
"""

import json
import re
import sys
from collections import deque
import tempfile
import time
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
EXISTS = sys.modules["xbmcvfs"].exists  # the stub's, for paths not a test's pictures
sys.path.insert(0, str(HELPER))

from resources.lib.apis import cache, wikidata  # noqa: E402
from resources.lib.apis.http import HttpError  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.script import actions  # noqa: E402
from resources.lib.shared import art_details as art  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402

FIXTURE = json.loads((HELPER / "tests/fixtures/wikidata_works.json").read_text("utf-8"))
ARTIST = json.loads((HELPER / "tests/fixtures/wikidata_artist.json").read_text("utf-8"))
TURNER = "Q159758"
MONTHS = dict(
    enumerate(
        "January February March April May June July August "
        "September October November December".split(),
        21,
    )
)  # Kodi's strings 21-32
HOME = sys.modules["xbmcgui"].Window(10000)
FOLDER = "/pictures/Art/"
ALIVE = lambda: True  # a look-up's live test that never stops it
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


PAINTERS = {  # a painter's Q-id → its fixture entry
    artist["qid"]: artist
    for artist in FIXTURE["artists"].values()
    if isinstance(artist, dict)
}


def search_rows(search):
    """The search query's row: the painter a search finds, if any."""
    artist = FIXTURE["artists"].get(search, {})
    if isinstance(artist, str):  # the right spelling finds what the fuzzy one does
        artist = FIXTURE["artists"][artist]
    if not artist:
        return []
    return [
        {
            "artist": literal(wikidata.ENTITY + artist["qid"]),
            "artistLabel": literal(artist["label"], "en"),
        }
    ]


def works_rows(qid):
    """The works query's rows for a painter, as the query service answers them."""
    rows = []
    for work, links, years, labels in PAINTERS[qid]["works"]:
        row = {
            "work": literal(wikidata.ENTITY + work),
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


def rows(names, fixture):
    """Fixture rows as bindings, an empty field unbound (an OPTIONAL with no match)."""
    return [
        {name: literal(text) for name, text in zip(names, row) if text}
        for row in fixture
    ]


# A rail's query, by what only it asks
RAIL_QUERIES = {"?notable": "gallery", "wdt:P135 ?movement": "similar"}


class ArtDetailsTest(unittest.TestCase):
    """Wikidata and Wikipedia answer from the fixture; each request is in self.asked."""

    def setUp(self):
        self.asked, self.refuse, self.gone = [], None, set()
        ApiCacheHandler().clear("wikidata:%")
        art.FOLDERS.unlink(missing_ok=True)
        for queue in (wikidata.NEXT_CALL, f"{wikidata.NEXT_CALL}.held"):
            HOME.clearProperty(queue)
        MTIMES.clear()
        for target, name, value in (
            (wikidata.http, "get_json", self.answer),
            (handlers, "set_items", lambda items, **kwargs: items),
            (handlers.ADDON, "getSettingBool", lambda key: key == "wikidata"),
            (wikidata, "NEXT_CALL", ""),  # no queue: a test asks faster than 1 a second
            (art.xbmcvfs, "exists", self.exists),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def exists(self, path):
        """xbmcvfs.exists: the test's pictures are on disk, but those gone."""
        return path not in self.gone if path.startswith(FOLDER) else EXISTS(path)

    def answer(self, url, params=None, headers=None, timeout=5, body=None):
        if self.refuse:
            raise self.refuse
        if url == wikidata.SPARQL:
            query = params["query"]
            if qid := re.search(r"VALUES \?work \{ wd:(Q\d+) \}", query):
                self.asked.append(f"painting {qid[1]}")
                return {"results": {"bindings": painting_rows(qid[1])}}
            qid = re.search(r"VALUES \?artist \{ wd:(Q\d+) \}", query)
            if '"born" AS ?kind' in query:
                self.asked.append(f"artist {qid[1]}")
                names = "kind", "value", "valueLabel", "precision", "calendar"
                names += "country", "since"
                bindings = rows(names, ARTIST["pages"].get(qid[1], []))
                return {"results": {"bindings": bindings}}
            if "wikibase:sitelinks ?links" in query and "?labels" not in query:
                kind = next(
                    (k for text, k in RAIL_QUERIES.items() if text in query),
                    "influenced",
                )
                self.asked.append(f"{kind} {qid[1]}")
                names = "item", "label", "image", "year"
                bindings = rows(names, ARTIST["rails"].get(f"{kind}:{qid[1]}", []))
                return {"results": {"bindings": bindings}}
            if qid:
                self.asked.append(f"works {qid[1]}")
                return {"results": {"bindings": works_rows(qid[1])}}
            search = re.search(r'srsearch "(.+?) haswbstatement', query)[1]
            self.asked.append(f"search {search}")
            return {"results": {"bindings": search_rows(search)}}
        title = unquote(url.removeprefix(wikidata.SUMMARY)).replace("_", " ")
        self.asked.append(f"summary {title}")
        summaries = FIXTURE["summaries"] | ARTIST["summaries"]
        if title not in summaries:
            raise HttpError(404)
        return {"extract": summaries[title]}

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
                artist = wikidata.works(art.parse(name).artist, ALIVE)
                found = art.match(art.parse(name), artist["works"])
                self.assertEqual(found and found[0], qid)

    def test_fuzzy_artist(self):
        artist = wikidata.works("Wassily Kandinksy", ALIVE)
        self.assertEqual(artist["label"], "Wassily Kandinsky")
        self.assertEqual(
            self.asked,
            ["search Wassily Kandinksy", "search Wassily~ Kandinksy~", "works Q61064"],
        )
        # each search is a request of its own, kept under its own key; the works too
        cache_row = ApiCacheHandler().get
        self.assertEqual(cache_row("wikidata:artist:wassilykandinksy")[0], {})
        self.assertTrue(cache_row("wikidata:fuzzy:wassilykandinksy")[0])
        self.asked = []
        wikidata.works("Wassily Kandinsky", ALIVE)  # the right spelling: the same works
        self.assertEqual(self.asked, ["search Wassily Kandinsky"])

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
                works = wikidata.works(parsed.artist, ALIVE)["works"]
                self.assertIsNone(art.match(parsed, works))
        # the re-review's probe: a Green Forest of the file's own year, 1912
        yellow = art.parse("Natalia Goncharova - 'Yellow and Green Forest' (1912).jpg")
        forest = [["Q900031", 2, [1912], ["Green Forest"]]]
        title = art.words(yellow.title)
        self.assertEqual(art.title_score(title, ["Green Forest"]), art.SHARE_MAX)
        self.assertIsNone(art.match(yellow, forest))  # 0.6 + 0.15 = 0.75

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
        found = art.look_up(path, ALIVE)
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
        found = art.look_up(path, ALIVE)
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
        found = art.look_up(
            f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg", ALIVE
        )
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
        self.assertEqual(art.look_up(path, ALIVE)["qid"], "Q2358487")
        asked = len(self.asked)
        self.assertEqual(art.verdict(path)["qid"], "Q2358487")
        self.assertEqual(len(self.asked), asked)  # from the cache
        MTIMES[path] = 200  # the file changed
        self.assertIsNone(art.verdict(path))

    def test_a_miss_is_kept(self):
        path = f"{FOLDER}Natalia Goncharova - Los Gatos (1913).jpg"
        self.assertEqual(art.look_up(path, ALIVE), {})
        self.assertEqual(art.verdict(path), {})
        self.assertEqual(
            art.look_up("/pictures/IMG_2041.jpg", ALIVE), {}
        )  # no artist: no ask
        self.assertEqual(self.asked, ["search Natalia Goncharova", "works Q232391"])
        self.assertEqual(art.look_up(f"{FOLDER}Nobody Known - Untitled.jpg", ALIVE), {})

    def test_no_answer_keeps_no_verdict(self):
        path = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg"
        self.refuse = HttpError(None)  # unreachable
        self.assertIsNone(art.look_up(path, ALIVE))
        self.assertIsNone(art.verdict(path))
        self.refuse, self.asked = None, []
        self.assertIsNone(
            art.look_up(path, ALIVE)
        )  # within the failure's wait: not asked
        self.assertEqual(self.asked, [])
        ApiCacheHandler().expire("wikidata:%")  # the wait is over
        self.assertEqual(art.look_up(path, ALIVE)["qid"], "Q28839414")

    def test_429_holds_the_queue_and_the_look_up_waits_it_out(self):
        # a busy queue, as a 429 holds it: the look-up, aside, waits a second at a
        # time while it is live (wikidata_details.answer), then asks once it frees
        path, queue, waits = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg", "q.next", []
        self.addCleanup(HOME.clearProperty, queue)
        self.addCleanup(HOME.clearProperty, f"{queue}.held")

        def wait(monitor, seconds=0):
            if seconds == 1:  # the look-up's, not a queued request's
                self.assertEqual(self.asked, [])  # nothing sent while the hold stands
                self.refuse = None
                HOME.setProperty(queue, "0")  # the hold passes
                HOME.setProperty(f"{queue}.held", "0")
            waits.append(seconds)
            return False

        self.refuse = HttpError(429, retry_after=60)
        with (
            mock.patch.object(wikidata, "NEXT_CALL", queue),
            mock.patch.object(Monitor, "waitForAbort", wait),
        ):
            self.assertEqual(art.look_up(path, ALIVE)["qid"], "Q28839414")
        self.assertEqual(waits.count(1), 1)
        self.assertEqual(self.asked[0], "search Franz Marc")  # asked again, once

    def test_stopped_during_the_queue_wait_asks_nothing(self):
        on = [True]
        queue = mock.patch.object(wikidata, "NEXT_CALL", "copacetic.wikidata_next")
        queue.start()
        self.addCleanup(queue.stop)
        HOME.setProperty(wikidata.NEXT_CALL, f"{time.time() + 1}")  # a slot ahead

        def off(monitor, seconds):
            on[0] = False  # the setting turned off while the call waits its slot
            return False

        with mock.patch.object(Monitor, "waitForAbort", off):
            path = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg"
            self.assertIsNone(art.look_up(path, lambda: on[0]))
        self.assertEqual(self.asked, [])

    def test_stopped_during_the_last_wait_keeps_no_verdict(self):
        # the last call's stale row (no works listed) comes back: no miss is kept
        on, cache_ = [True], ApiCacheHandler()
        queue = mock.patch.object(wikidata, "NEXT_CALL", "copacetic.wikidata_next")
        queue.start()
        self.addCleanup(queue.stop)
        painter = {"qid": "Q44054", "label": ""}  # found, fresh
        cache_.put("wikidata:artist:franzmarc", painter, cache.DAY)
        cache_.put("wikidata:works:Q44054", [], -10)
        HOME.setProperty(wikidata.NEXT_CALL, f"{time.time() + 1}")  # a slot ahead

        def off(monitor, seconds):
            on[0] = False
            return False

        path = f"{FOLDER}Franz Marc - 'Foxes' (1913).jpg"
        with mock.patch.object(Monitor, "waitForAbort", off):
            self.assertIsNone(art.look_up(path, lambda: on[0]))
        self.assertEqual((self.asked, art.verdict(path)), ([], None))

    def test_refresh(self):
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        art.look_up(path, ALIVE)
        self.asked = []
        actions.art_details_refresh(path)  # the folder isn't marked: nothing sent
        self.assertEqual(self.asked, [])
        art.mark(FOLDER, True)
        with mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: False):
            actions.art_details_refresh(path)  # the setting off: nothing sent
        self.assertEqual(self.asked, [])
        HOME.setProperty("art_details_refresh", path)  # read as written, no decode
        actions.art_details_refresh(prop="art_details_refresh")
        self.assertEqual(
            self.asked, ["search Franz Marc", "works Q44054", "painting Q2358487"]
        )
        self.assertEqual(art.verdict(path)["qid"], "Q2358487")

    def test_forget_drops_its_own_file_only(self):
        mine, other = f"{FOLDER}Tiger_%.jpg", f"{FOLDER}TigerX12.jpg"  # LIKE would
        for path in (mine, other):
            art.look_up(path, ALIVE)  # no " - ": a miss, kept
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
        art.look_up(path, ALIVE)
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
        # no folder (picture info over the slideshow): the listing's state stays
        query = f"info=art_details&path={path}"
        plugin = handlers.PluginHandlers({"info": "art_details"}, query=query)
        HOME.setProperty("art_details_checked", "/listing/")
        self.assertEqual(
            plugin.art_details()[0]["properties"]["art_title"], "The Starry Night"
        )
        self.assertEqual(HOME.getProperty("art_details_checked"), "/listing/")

    def asides(self):
        """The aside workers not started; the test drains them by hand."""
        started = []
        thread = lambda target, daemon: mock.Mock(start=lambda: started.append(target))
        patcher = mock.patch.object(cache, "Thread", thread)
        patcher.start()
        self.addCleanup(patcher.stop)
        for queue in (art.ASIDES, art.PAGES):
            self.addCleanup(queue.asked.clear)
            self.addCleanup(queue.queue.clear)
            self.addCleanup(setattr, queue, "running", 0)
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
        self.assertEqual((self.asked, gone.call_count), ([], 1))  # owed, not fetched
        art.mark(FOLDER, False)  # unmarked while it waited: still nothing sent
        waiting = mock.Mock(current=lambda: True)
        art.ASIDES.ask(path, waiting)
        art.ASIDES._drain()
        self.assertEqual((self.asked, waiting.call_count), ([], 0))

    def test_an_asker_that_raises_spoils_no_other_ask(self):
        self.asides()
        queue = cache.Asides(lambda key, live: key.upper())
        later = mock.Mock(current=lambda: True)

        def boom():
            queue.ask("a", later)  # a newer arrival asks while this one is told
            raise RuntimeError("an asker")

        first = mock.Mock(current=lambda: True, side_effect=boom)
        other = mock.Mock(current=lambda: True)
        queue.ask("a", first)
        queue.ask("a", other)
        with mock.patch.object(cache.log, "exception") as logged:
            queue._drain()
        logged.assert_called_once()  # the error, with its traceback
        other.assert_called_once()  # told, whatever the first did
        later.assert_called_once()  # its own fetch, in turn: not dropped
        self.assertEqual((queue.asked, queue.running), ({}, 0))

    def test_a_look_up_stops_when_the_setting_turns_off(self):
        self.asides()
        art.mark(FOLDER, True)
        on, answer = [True], self.answer

        def then_off(*args, **kwargs):
            found = answer(*args, **kwargs)
            on[0] = False  # turned off once the search has answered
            return found

        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        asker = mock.Mock(current=lambda: True)
        with (
            mock.patch.object(wikidata.http, "get_json", then_off),
            mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: on[0]),
        ):
            art.ASIDES.ask(path, asker)
            art.ASIDES._drain()
        self.assertEqual(
            self.asked, ["search Franz Marc"]
        )  # no works, painting, summary
        self.assertIsNone(art.verdict(path))  # no verdict: the next visit asks again
        asker.assert_not_called()

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
        art.look_up(path, ALIVE)
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

    # Artist page

    def artist(self, params="", again=None):
        """The art_artist serve's item for Turner."""
        query = f"info=art_artist&qid={TURNER}{params}"
        plugin = handlers.PluginHandlers(
            dict(p.split("=", 1) for p in query.split("&")), again=again, query=query
        )
        return plugin.art_artist()[0]

    def rail(self, kind, again=None):
        """The art_rail serve's items for one of Turner's rails."""
        params = {"info": "art_rail", "kind": kind, "qid": TURNER}
        return list(handlers.PluginHandlers(params, again=again).art_rail())

    def test_artist_page(self):
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            art._ask(("painter", TURNER), ALIVE)
            item = self.artist()
        self.assertEqual(self.asked, [f"artist {TURNER}", "summary J. M. W. Turner"])
        self.assertEqual(item["label"], "J. M. W. Turner")
        self.assertEqual(
            item["art"]["thumb"],
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Turner%20selfportrait.jpg?width=1280",
        )
        props = item["properties"]
        self.assertEqual(
            {
                k.removeprefix("art_"): v
                for k, v in props.items()
                if k != "art_biography"
            },
            {
                "name": "J. M. W. Turner",
                "occupation": "Painter",  # painter first, whatever Wikidata's order
                "life": "1775–1851",
                "born": "23 April 1775, Maiden Lane, London",  # the unknown place out
                "died": "1851, Cheyne Walk, London",  # year-precise: the year alone
                "teacher": "Joshua Reynolds, Thomas Malton",  # the unlabelled one out
                "teacher_more": "1",
                "movement": "Romanticism",
                "movement_more": "1",
                "nationality": "British",
                "paintings": "575",
                "influence": "Claude Lorrain, Thomas Girtin",
                "influence_more": "",
            },
        )
        self.assertTrue(props["art_biography"].startswith("Joseph Mallord William"))

    def test_first_country_and_a_death_alone(self):
        found = {
            "name": ["Wassily Kandinsky"],
            "died": [["1944-12-13T00:00:00Z", 11]],
            "nationality": [  # as the query answers: no set order
                ["Q183", 1928, "German"],
                ["Q34266", 0, "Russian"],
                ["Q142", 1939, "French"],
            ],
            "biography": "",
        }
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            fields = art.artist_fields(found)
        self.assertEqual(fields["nationality"], "Russian")  # no start: the first
        self.assertEqual(fields["life"], "–1944")  # the death year alone
        self.assertEqual((fields["born"], fields["died"]), ("", "13 December 1944"))

    def test_refresh_marks_the_artist_page_stale(self):
        art.mark(FOLDER, True)
        path = f"{FOLDER}Franz Marc - 'Tiger' (1912).jpg"
        art.look_up(path, ALIVE)
        painter = art.verdict(path)["artist_qid"]
        cache_put = ApiCacheHandler().put
        cache_put(f"wikidata:painter:{painter}", {"enwiki": ["Franz Marc"]}, 600)
        cache_put("wikidata:summary:franzmarc", "Franz Marc was a painter.", 600)
        for kind in wikidata.RAILS:
            cache_put(f"wikidata:{kind}:{painter}", [], 600)
        page = [
            ("painter", painter),
            ("summary", "Franz Marc"),
            *((kind, painter) for kind in wikidata.RAILS),
        ]
        self.assertTrue(all(wikidata.kept(*key)[1] for key in page))  # fresh
        actions.art_details_refresh(path)
        for key in page:
            with self.subTest(key=key):
                self.assertFalse(wikidata.kept(*key)[1])  # stale: asked again

    def test_served_artist_asks_aside_once(self):
        started = self.asides()
        asker = mock.Mock(current=lambda: True)
        self.assertEqual(self.artist()["properties"], {})  # a plugin call: kept only
        self.assertEqual((self.asked, started), ([], []))
        self.assertEqual(self.artist(again=asker)["properties"], {})  # none yet
        self.assertEqual(self.asked, [])  # the serve itself sends nothing
        art.PAGES._drain()
        asker.assert_called_once()
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            props = self.artist(again=asker)["properties"]
        self.assertEqual(props["art_name"], "J. M. W. Turner")
        self.assertEqual(len(started), 1)  # fresh: no second ask
        ApiCacheHandler().expire(f"wikidata:painter:{TURNER}")
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            self.artist(again=asker)  # stale: served, and asked again
        art.PAGES._drain()
        asker.assert_called_once()  # the same answer: no news

    def test_artist_page_stops_when_the_setting_turns_off(self):
        on, answer = [True], self.answer

        def then_off(*args, **kwargs):
            found = answer(*args, **kwargs)
            on[0] = False  # turned off once the artist has answered
            return found

        with (
            mock.patch.object(wikidata.http, "get_json", then_off),
            mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: on[0]),
        ):
            art._ask(("painter", TURNER), ALIVE)
            self.assertIsNone(art._ask(("gallery", TURNER), ALIVE))
        self.assertEqual(self.asked, [f"artist {TURNER}"])  # no summary, no rail

    # Search

    def found(self, query):
        """The search's hits, by file name."""
        return [Path(path).name for path, _ in art.search(query, handlers.SEARCH_LIMIT)]

    def test_search_reads_kept_verdicts_only(self):
        art.mark(FOLDER, True)
        starry, tiger, gatos = (
            "Vincent Van Gogh - 'Starry Night' (1890).jpg",
            "Franz Marc - 'Tiger' (1912).jpg",
            "Natalia Goncharova - Los Gatos (1913).jpg",  # a miss
        )
        for name in (starry, tiger, gatos):
            art.look_up(f"{FOLDER}{name}", ALIVE)
        page = {"movement": [["Q1", "Der Blaue Reiter"]]}
        ApiCacheHandler().put("wikidata:painter:Q44054", page, 600)
        self.asked = []
        self.assertEqual(self.found("starry"), [starry])  # the title
        self.assertEqual(self.found("van gogh"), [starry])  # the artist, word by word
        self.assertEqual(self.found("moon"), [starry])  # what it depicts
        self.assertEqual(self.found("modern art"), [starry])  # its collection
        self.assertEqual(self.found("blaue"), [tiger])  # its artist's kept movement
        self.assertEqual(self.found("gatos"), [gatos])  # a miss, by its file name
        # title, then artist, then the details, then the name; matches first
        self.assertEqual(self.found("a"), [starry, tiger, gatos])
        self.assertEqual(
            self.found(""), [tiger, starry]
        )  # no words: matches, by artist
        self.assertEqual(self.found("🌻 ⭐"), [])  # emoji alone: no word, no match
        self.assertEqual(self.found("cypress tiger"), [])  # every word, in one tier
        self.assertEqual(self.asked, [])  # nothing asked
        kept = ApiCacheHandler().get(f"wikidata:file:{FOLDER}{tiger}")[0]
        ApiCacheHandler().put(f"wikidata:file:{FOLDER}Tiger.mp4", kept, 600)
        self.assertEqual(self.found("tiger"), [tiger])  # a kept video never shows
        art.mark(FOLDER, False)
        self.assertEqual(self.found("starry"), [])  # marked folders only

    def test_search_serve(self):
        art.mark(FOLDER, True)
        path = f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg"
        art.look_up(path, ALIVE)
        plugin = handlers.PluginHandlers({"info": "art_search", "query": "starry"})
        (item,) = plugin.art_search()
        self.assertEqual(item["file"], path)  # Kodi's select shows the picture
        self.assertEqual(
            (item["label"], item["label2"]), ("The Starry Night", "Vincent van Gogh")
        )
        self.assertEqual(item["properties"]["art_year"], "1889")
        self.assertNotIn("art_summary", item["properties"])  # a rail shows none
        with mock.patch.object(handlers.ADDON, "getSettingBool", lambda key: False):
            self.assertEqual(list(plugin.art_search()), [])

    def test_search_query_and_limit(self):
        art.mark(FOLDER, True)
        rhone = f"{FOLDER}Vincent Van Gogh - 'Starry Night over The Rhone' (1888).jpg"
        starry = f"{FOLDER}Vincent Van Gogh - 'Starry Night' (1890).jpg"
        for path in (rhone, starry):
            art.look_up(path, ALIVE)

        def files(**params):
            plugin = handlers.PluginHandlers({"info": "art_search"} | params)
            return [item["file"] for item in plugin.art_search()]

        # set_search_query's JSON escapes, once Kodi's percent-encoding is decoded
        self.assertEqual(files(query="Rh\\u00f4ne"), [rhone])
        self.assertEqual(len(files(query="starry")), 2)
        self.assertEqual(files(query="starry", limit="1"), [rhone])  # the rail's limit
        self.gone.add(rhone)  # moved or deleted: dropped, the next one in its place
        self.assertEqual(files(query="starry", limit="1"), [starry])
        # Past U+FFFF: a surrogate pair of escapes, as _publish_query writes it
        rare = f"{FOLDER}Rare.jpg"
        kept = ApiCacheHandler().get(f"wikidata:file:{starry}")[0]
        kept["fields"] |= {"title": "Night \U00020000"}
        ApiCacheHandler().put(f"wikidata:file:{rare}", kept, 600)
        actions._publish_query("\U00020000 night", 1)
        self.assertEqual(files(query=unquote(HOME.getProperty("search_query"))), [rare])

    def test_refresh_pictures_only(self):
        art.mark(FOLDER, True)
        actions.art_details_refresh(f"{FOLDER}Franz Marc - 'Tiger' (1912).mp4")
        self.assertEqual(self.asked, [])  # a video is never looked up

    def test_prefix_rows_exactly(self):
        cache = ApiCacheHandler()
        for key in ("x:a_b", "x:a%b", "x:aXb", "x:b"):
            cache.put(key, 1, 600)
        self.assertEqual([k for k, _ in cache.starting("x:a_")], ["x:a_b"])
        self.assertEqual([k for k, _ in cache.starting("x:a%")], ["x:a%b"])
        cache.clear("x:%")

    def test_rails(self):
        self.asides()
        asker = mock.Mock(current=lambda: True)
        self.assertEqual(self.rail("gallery", again=asker), [])
        art.PAGES._drain()
        dido, untitled = self.rail("gallery", again=asker)
        self.assertEqual(
            (dido["label"], dido["label2"]), ("Dido Building Carthage", "1815")
        )
        self.assertEqual(
            dido["properties"],
            {
                "qid": "Q910201",
                "full": "https://commons.wikimedia.org/wiki/Special:FilePath/"
                "Dido%20building%20Carthage.jpg?width=1920",
            },
        )
        self.assertEqual(untitled["label"], "")  # no English label: art only
        art._ask(("similar", TURNER), ALIVE)
        art._ask(("influenced", TURNER), ALIVE)
        self.assertEqual([i["label"] for i in self.rail("similar")], ["John Constable"])
        self.assertEqual(self.rail("influenced"), [])  # none: an empty rail
        self.assertEqual(self.rail("works"), [])  # not a rail: nothing asked
        self.assertEqual(
            self.asked,
            [f"gallery {TURNER}", f"similar {TURNER}", f"influenced {TURNER}"],
        )

    def test_similar_painters_only(self):
        query = wikidata.RAILS["similar"]
        self.assertIn("wdt:P106 wd:%(painter)s", query)  # the occupation, and
        self.assertIn("?work wdt:P170 ?item; wdt:P31 wd:%(painting)s", query)  # works,
        self.assertIn("HAVING(COUNT(DISTINCT ?work) >= %(paintings)s)", query)  # five
        self.assertIn("<= %(years)s", query)
        for kind in ("similar", "influenced"):  # an artist always has a name to open
            label = 'rdfs:label ?name FILTER(LANG(?name) = "en")'
            self.assertIn(label, wikidata.RAILS[kind])
            self.assertNotIn("OPTIONAL { ?item rdfs:label", wikidata.RAILS[kind])

    def test_date_precision(self):
        time = "1650-01-01T00:00:00Z"
        self.assertEqual(art._date(time, 7), "17th century")
        self.assertEqual(art._date("1700-01-01T00:00:00Z", 7), "17th century")
        self.assertEqual(art._date("1901-01-01T00:00:00Z", 7), "20th century")
        self.assertEqual(art._date("1101-01-01T00:00:00Z", 7), "12th century")
        self.assertEqual(art._date("1001-01-01T00:00:00Z", 7), "11th century")
        self.assertEqual(art._date(time, 8), "1650s")
        self.assertEqual(art._date("1655-01-01T00:00:00Z", 8), "1650s")
        self.assertEqual(art._date(time, 9), "1650")
        found = {"born": [[time, 8]], "died": [["1688-05-02T00:00:00Z", 11]]}
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            fields = art.artist_fields(found | {"biography": ""})
        self.assertEqual(fields["life"], "1650s–1688")  # each to its precision

    def test_dates_bc(self):
        # A century or decade keeps Wikidata's own numbering (-500 is 500 BC)
        for year, century, decade in (
            ("-0500", "5th century BC", "500s BC"),
            ("-0501", "6th century BC", "500s BC"),
            ("-0005", "1st century BC", "0s BC"),
        ):
            time = f"{year}-01-01T00:00:00Z"
            with self.subTest(year=year):
                self.assertEqual(art._date(time, 7), century)
                self.assertEqual(art._date(time, 8), decade)
        # A year or finer is astronomical in the query service's answer: 0 is 1 BC
        for year, text in (("0000", "1 BC"), ("-0043", "44 BC"), ("-0500", "501 BC")):
            with self.subTest(year=year):
                self.assertEqual(art._date(f"{year}-01-01T00:00:00Z", 9), text)

    def test_julian_dates(self):
        julian = wikidata.JULIAN
        with mock.patch.object(art, "getLocalizedString", MONTHS.get):
            # Caesar's death as the query service gives it: Julian 15 March 44 BC
            caesar = "-0043-03-13T00:00:00Z"
            self.assertEqual(art._date(caesar, 11, julian), "15 March 44 BC")
            self.assertEqual(art._date(caesar, 11, julian, limit=9), "44 BC")
            year = "-0043-01-01T00:00:00Z"  # a year is never converted
            self.assertEqual(art._date(year, 9, julian), "44 BC")
            # Michelangelo's birth, Julian 6 March 1475: Gregorian 15 March
            michelangelo = "1475-03-15T00:00:00Z"
            self.assertEqual(art._date(michelangelo, 11, julian), "6 March 1475")
            # A Gregorian date, and one kept before calendars, as given
            turner = "1775-04-23T00:00:00Z"
            self.assertEqual(art._date(turner, 11, "Q1985727"), "23 April 1775")
            self.assertEqual(art._date(turner, 11), "23 April 1775")
            # Near the new year: Julian 25 December 1599 is Gregorian 4 January 1600
            christmas = "1600-01-04T00:00:00Z"
            self.assertEqual(art._date(christmas, 11, julian), "25 December 1599")
            self.assertEqual(art._date(christmas, 11, julian, limit=9), "1599")

    def test_artist_history(self):
        sent = []
        HOME.setProperty("page_artist", TURNER)
        HOME.clearProperty("page_artist_back")
        with mock.patch("resources.lib.service.serve.ring", sent.append):
            actions.art_artist(prop="page_artist", qid="Q159606", ring="serve?x")
            actions.art_artist(prop="page_artist", qid="Q159606")  # shown: nothing
            actions.art_artist(prop="page_artist", qid="Q5582")
        self.assertEqual(HOME.getProperty("page_artist"), "Q5582")
        self.assertEqual(HOME.getProperty("page_artist_back"), f"{TURNER} Q159606")
        self.assertEqual(sent, ["serve?x"])
        actions.art_artist(prop="page_artist")  # Back
        actions.art_artist(prop="page_artist")
        self.assertEqual(HOME.getProperty("page_artist"), TURNER)
        self.assertEqual(HOME.getProperty("page_artist_back"), "")
        actions.art_artist(prop="page_artist")  # none left: the skin closes the page
        self.assertEqual(HOME.getProperty("page_artist"), TURNER)
        for n in range(actions.ARTIST_HISTORY + 2):
            actions.art_artist(prop="page_artist", qid=f"Q{n}")
        self.assertEqual(
            len(HOME.getProperty("page_artist_back").split()), actions.ARTIST_HISTORY
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)
