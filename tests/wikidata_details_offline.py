"""
Offline checks for Wikidata details (apis/wikidata.py's having, items and labels;
shared/wikidata_details.py; the metadata serve's wikidata=true and
compilation_artists=true; the soundtracks listing's second pass): items found by
TMDb, IMDb and MusicBrainz ids, never by a query; labels in English, else
multilingual, else any language; Based on from written works only, worded by the
item's title; Set in; Music by; an artist's labels (+N) and place; an album's
producers; a compilation's track artists from the library; a served item's details
kept, missing ones asked aside; the soundtrack id link both ways and the composer
tie-break, and the title matching alone with the setting off or Wikidata down.

Wikidata answers from tests/fixtures/wikidata_details.json (items as wbgetentities
gives them; see its note), the statement search worked out from their statements;
the library is hand-written in Omega's JSON-RPC shape. Run from the helper root:
python tests/wikidata_details_offline.py
"""

import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)


class Monitor:
    """Kodi's Monitor: never exiting, and a wait returns at once."""

    def abortRequested(self):
        return False

    def waitForAbort(self, seconds=0):
        return False


vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Monitor=Monitor,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.modules["xbmcvfs"].mkdirs = lambda path: Path(path).mkdir(exist_ok=True) or 1
sys.path.insert(0, str(HELPER))

from resources.lib.apis import cache, wikidata  # noqa: E402
from resources.lib.apis.http import HttpError  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.shared import helpers  # noqa: E402
from resources.lib.shared import wikidata_details as wd  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402

FIXTURE = json.loads(
    (HELPER / "tests/fixtures/wikidata_details.json").read_text("utf-8")
)
ALIVE = lambda: True  # a look-up's live test that never stops it
ZIMMER = "e6de1f3b-6484-491c-88dd-6d619f142abc"  # Hans Zimmer's MusicBrainz id
DAFT_PUNK = "056e4f3e-d505-4dad-8ec1-d04f521cbb56"
DUNE = ("movie", "438631", "")  # Dune (2021) by its TMDb id
SLOW_HORSES = ("tvshow", "95480", "tt5875444")


def item(qid, label, **claims):
    """An item as wbgetentities gives it: an English label, statements by property."""
    statements = {
        prop: [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": prop,
                    "datavalue": (
                        {"value": {"id": value}, "type": "wikibase-entityid"}
                        if value[:1] == "Q"
                        else {"value": value, "type": "string"}
                    ),
                },
                "rank": "normal",
            }
            for value in values
        ]
        for prop, values in claims.items()
    }
    labels = {"en": {"language": "en", "value": label}} if label else {}
    return {"type": "item", "id": qid, "labels": labels, "claims": statements}


class WikidataCase(unittest.TestCase):
    """Wikidata answers from the fixture; each request is in self.asked."""

    def setUp(self):
        self.asked, self.refuse, self.setting = [], None, True
        self.entities = copy.deepcopy(FIXTURE["entities"])
        ApiCacheHandler().clear("wikidata:%")
        for target, name, value in (
            (wikidata.http, "get_json", self.answer),
            (
                wd.ADDON,
                "getSettingBool",
                lambda key: key == "wikidata" and self.setting,
            ),
            (wikidata, "NEXT_CALL", ""),  # no queue: a test asks faster than 1 a second
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def answer(self, url, params=None, headers=None, timeout=5, body=None):
        self.assertEqual(url, wikidata.API)  # by the wiki's API: never a query
        self.assertEqual(timeout, wikidata.API_TIMEOUT)
        if self.refuse:
            raise self.refuse
        if params["action"] == "query":
            statement = params["srsearch"].removeprefix("haswbstatement:")
            self.asked.append(f"having {statement}")
            prop, value = statement.split("=")
            found = [
                qid
                for qid, entity in self.entities.items()
                if value in map(self.value, entity["claims"].get(prop, []))
            ]
            hits = [{"ns": 0, "title": qid, "pageid": 1} for qid in found]
            return {"batchcomplete": "", "query": {"search": hits}}
        self.assertEqual(params["action"], "wbgetentities")
        self.asked.append(f"{params['props']} {params['ids']}")
        entities = {}
        for qid in params["ids"].split("|"):
            entity = self.entities.get(qid, {"id": qid, "missing": ""})
            if params["props"] == "labels":
                entity = {
                    key: value for key, value in entity.items() if key != "claims"
                }
            if "labels" in entity and "languages" in params:
                languages = params["languages"].split("|")
                names = entity["labels"].items()
                labels = {code: name for code, name in names if code in languages}
                entity = entity | {"labels": labels}
            entities[qid] = entity
        return {"entities": entities, "success": 1}

    @staticmethod
    def value(statement):
        """A statement's value as the search matches it: a Q-id or a string."""
        value = statement["mainsnak"]["datavalue"]["value"]
        return value["id"] if isinstance(value, dict) else value


class DetailsTest(WikidataCase):
    def test_a_show_by_tmdb_id(self):
        found = wd.details(SLOW_HORSES, ALIVE)
        self.assertEqual(
            found["source"],
            {"title": "Slow Horses", "type": "novel", "authors": ["Mick Herron"]},
        )
        self.assertEqual(
            wd.properties("tvshow", found, "Slow Horses"),
            {
                "wikidata_based_on": "the novel by Mick Herron",
                "wikidata_set_in": "London",
            },
        )
        # five requests, none a query; the place by its label alone
        self.assertEqual(
            self.asked,
            [
                "having P4983=95480",
                "labels|claims Q104880809",
                "having P9899=Q104880809",
                "labels|claims Q108063656",
                "labels Q24929761|Q84",
            ],
        )
        self.asked.clear()
        self.assertEqual(wd.details(SLOW_HORSES, ALIVE), found)  # kept
        self.assertEqual(self.asked, [])

    def test_a_film(self):
        found = wd.details(DUNE, ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        self.assertEqual(found["composers"], [ZIMMER])
        self.assertEqual(found["set_in"], "Arrakis")  # P840's first
        self.assertEqual(found["soundtracks"], ["6790ad81-5b9c-4362-87c0-6c8e8d3d4100"])
        self.assertEqual(
            wd.properties("movie", found, "Dune"),
            {
                "wikidata_music_by": "Hans Zimmer",
                "wikidata_based_on": "the novel by Frank Herbert",
                "wikidata_set_in": "Arrakis",
            },
        )
        # films only: the TV details grid has no Music by cell
        self.assertNotIn("wikidata_music_by", wd.properties("tvshow", found, "Dune"))
        # a title other than the work's names it, case and punctuation aside
        self.assertEqual(
            wd.properties("movie", found, "Dune: Part One")["wikidata_based_on"],
            "Dune, novel by Frank Herbert",
        )
        self.assertEqual(
            wd.properties("movie", found, "DUNE")["wikidata_based_on"],
            "the novel by Frank Herbert",
        )

    def test_imdb_when_tmdb_finds_none(self):
        found = wd.details(("movie", "999999", "tt1160419"), ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        self.assertEqual(
            self.asked[:2], ["having P4947=999999", "having P345=tt1160419"]
        )

    def test_no_item(self):
        self.assertEqual(wd.details(("movie", "999999", ""), ALIVE), {})
        self.assertEqual(wd.kept(("movie", "999999", "")), ({}, True))  # kept empty
        self.assertEqual(wd.properties("movie", {}, "Anything"), {})

    def test_written_works_only(self):
        # Backrooms: a web series, then a short story (a literary work in form)
        found = wd.details(("movie", "1083381", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found, "Backrooms")["wikidata_based_on"],
            "The Backrooms, short story",  # no author
        )
        # a manga's authors by " and "; Old Boy is Oldboy, spaces aside
        found = wd.details(("movie", "670", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found, "Oldboy")["wikidata_based_on"],
            "the manga by Garon Tsuchiya and Nobuaki Minegishi",
        )
        # a game, a character and a film are no source
        self.entities |= {
            "Q900": item("Q900", "Game Movie", P4947=["900"], P144=["Q901", "Q902"]),
            "Q901": item("Q901", "The Game", P31=["Q7889"]),  # video game
            "Q902": item("Q902", "The Hero", P31=["Q1114461"]),  # comics character
        }
        found = wd.details(("movie", "900", ""), ALIVE)
        self.assertIsNone(found["source"])
        self.assertEqual(wd.properties("movie", found, "Game Movie"), {})
        # a novel series is a written work
        self.entities |= {
            "Q904": item("Q904", "Series Movie", P4947=["904"], P144=["Q905"]),
            "Q905": item("Q905", "The Saga", P31=["Q1667921"]),
        }
        found = wd.details(("movie", "904", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found, "Series Movie")["wikidata_based_on"],
            "The Saga, novel series",
        )

    def test_the_type_word(self):
        self.assertEqual(
            wd._kind({"P31": ["Q7725634"], "P7937": ["Q149537"]}), "novella"
        )
        self.assertEqual(wd._kind({"P31": ["Q14406742"]}), "comic")
        self.assertEqual(wd._kind({"P31": ["Q1667921"]}), "novel series")
        self.assertEqual(wd._kind({"P31": ["Q277759"]}), "book series")
        self.assertEqual(wd._kind({"P31": ["Q7725634"], "P7937": ["Q1"]}), "book")
        source = {"title": "Room", "type": "novel", "authors": []}
        self.assertEqual(wd.based_on("Room", source), "the novel")

    def test_label_languages(self):
        # Despicable Me 4 and Pharrell Williams have no English label: multilingual
        found = wd.details(("movie", "519182", ""), ALIVE)
        self.assertEqual(found["music_by"], ["Heitor Pereira", "Pharrell Williams"])
        # Paris has only a French one here: any language
        found = wd.details(("artist", DAFT_PUNK), ALIVE)
        self.assertEqual(found["place"], "Paris")
        self.assertEqual(wikidata._shape({})["label"], "")

    def test_items_kept_one_by_one(self):
        wd.details(DUNE, ALIVE)
        self.asked.clear()
        # Inception's composer was kept with Dune: only its own items are asked
        found = wd.details(("movie", "999999", "tt1160419"), ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        zimmer = next(q for q, e in self.entities.items() if ZIMMER in str(e))
        self.assertFalse(any(zimmer in asked for asked in self.asked))
        # past BATCH, a request a batch; a missing item is an empty one
        qids = [f"Q{n}" for n in range(1, 2 * wikidata.BATCH + 2)]
        self.asked.clear()
        found = wikidata.items(qids)
        self.assertEqual(len(found), len(qids))
        self.assertEqual(found["Q1"], {"label": "", "claims": {}})
        self.assertEqual(len(self.asked), 3)
        self.asked.clear()
        self.assertEqual(wikidata.items(qids), found)  # kept
        self.assertEqual(self.asked, [])

    def test_an_album_linked_both_ways_once(self):
        found = wd.details(("movie", "519182", ""), ALIVE)
        self.assertEqual(found["soundtracks"], ["9128b04b-fd95-479c-963e-99dcdbf00849"])

    def test_artist_labels_and_place(self):
        found = wd.details(("artist", DAFT_PUNK), ALIVE)
        self.assertEqual(
            wd.properties("artist", found, "Daft Punk"),
            {
                "wikidata_labels": "Soma Quality Recordings, Virgin Records +2",
                "wikidata_place": "Paris",  # formed (P740)
            },
        )
        self.assertEqual(self.asked[-1], "labels Q847971|Q203059|Q90")  # two named
        self.entities |= {
            "Q910": item("Q910", "Duo", P434=["m-910"], P740=["Q84"], P19=["Q90"]),
            "Q911": item(
                "Q911", "Singer", P434=["m-911"], P19=["Q90"], P264=["Q54860"]
            ),
        }
        duo = wd.details(("artist", "m-910"), ALIVE)
        self.assertEqual((duo["place"], duo["labels"], duo["more"]), ("London", [], 0))
        self.assertEqual(
            wd.properties("artist", duo, "Duo"), {"wikidata_place": "London"}
        )
        singer = wd.details(("artist", "m-911"), ALIVE)  # born (P19)
        self.assertEqual(
            wd.properties("artist", singer, "Singer"),
            {"wikidata_labels": "Daft Life", "wikidata_place": "Paris"},
        )
        # an unlabelled one of the first two counts in +N
        self.entities |= {
            "Q912": item("Q912", "Trio", P434=["m-912"], P264=["Q913", "Q54860"]),
            "Q913": item("Q913", ""),
        }
        trio = wd.details(("artist", "m-912"), ALIVE)
        self.assertEqual(
            wd.properties("artist", trio, "Trio"), {"wikidata_labels": "Daft Life +1"}
        )
        # neither of the first two labelled: no bare "+N"
        self.entities |= {
            "Q914": item("Q914", "Quartet", P434=["m-914"], P264=["Q913", "Q915"]),
            "Q915": item("Q915", ""),
        }
        quartet = wd.details(("artist", "m-914"), ALIVE)
        self.assertEqual((quartet["labels"], quartet["more"]), ([], 2))
        self.assertEqual(wd.properties("artist", quartet, "Quartet"), {})

    def test_album_producer_and_films(self):
        found = wd.details(("album", "baf438d5-47ce-399c-9389-40a5d5f14632"), ALIVE)
        self.assertEqual(
            wd.properties("album", found, "Dune"), {"wikidata_producer": "Toto"}
        )
        # Dune (1984)'s P406 names it: its TMDb and IMDb ids
        self.assertCountEqual(
            found["films"], [["movie", "tmdb", "841"], ["", "imdb", "tt0087182"]]
        )
        found = wd.details(("album", "80aa8257-7bc5-39c0-87e1-95941e4c746c"), ALIVE)
        self.assertIn(["movie", "tmdb", "1443"], found["films"])  # its own P9899

    def test_unanswered_keeps_nothing(self):
        self.refuse = HttpError(503)
        self.assertIsNone(wd.details(DUNE, ALIVE))
        self.assertEqual(wd.kept(DUNE), (None, False))
        self.refuse = None
        stopped = iter([True, True, False])  # live for two requests, then not
        self.assertIsNone(wd.details(SLOW_HORSES, lambda: next(stopped)))
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(wd.kept(SLOW_HORSES), (None, False))

    def test_a_failure_is_not_asked_again(self):
        # only a 429's hold earns a second try: a failed batch keeps a row for its
        # first id only, so another try would send the rest again
        calls = []

        def refuse(*args, **kwargs):
            calls.append(args)
            raise HttpError(None)

        with mock.patch.object(wikidata.http, "get_json", refuse):
            with self.assertRaises(wd._Unanswered):
                wd._answer(ALIVE, wikidata.items, ["Q1", "Q2", "Q3"])
        self.assertEqual(len(calls), 1)

    def test_a_hold_during_the_wait_sends_nothing(self):
        # a call waiting its slot finds a 429 held the queue meanwhile: no request
        home, queue = cache.Window(10000), "test.wikidata_next"
        home.setProperty(queue, f"{time.time() + 2}")
        self.addCleanup(home.setProperty, f"{queue}.held", "0")

        def hold(monitor, seconds=0):
            home.setProperty(f"{queue}.held", f"{time.time() + 30}")
            return False

        with (
            mock.patch.object(wikidata, "NEXT_CALL", queue),
            mock.patch.object(Monitor, "waitForAbort", hold),
        ):
            self.assertIsNone(wikidata.having("P4947", "438631"))
        self.assertEqual(self.asked, [])

    def test_a_busy_queue_is_waited_out(self):
        # cached skips a request over MAX_WAIT ahead: the look-up, aside, waits a
        # second at a time while it is live, and asks once the queue frees
        home, queue, waits = cache.Window(10000), "test.wikidata_next", []
        home.setProperty(queue, f"{time.time() + 60}")

        def wait(monitor, seconds=0):
            waits.append(seconds)
            home.setProperty(queue, "0")
            return False

        with (
            mock.patch.object(wikidata, "NEXT_CALL", queue),
            mock.patch.object(Monitor, "waitForAbort", wait),
        ):
            found = wd.details(DUNE, ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        self.assertEqual(waits.count(1), 1)
        self.assertEqual(self.asked[0], "having P4947=438631")

    def test_a_429_is_waited_out_then_asked_again(self):
        # no failure row outlives the queue's slot: once it frees the look-up asks
        # again, after a long wait a second at a time, a short one in cached's wait
        home, queue = cache.Window(10000), "test.wikidata_next"

        def free(monitor, seconds=0):  # the wait's end: the slot and the hold pass
            home.setProperty(queue, "0")
            home.setProperty(f"{queue}.held", "0")
            return False

        for wait in (30, 2):
            ApiCacheHandler().clear("wikidata:%")
            home.setProperty(queue, "0")
            refused = iter([HttpError(429, wait)])

            def answer(*args, **kwargs):
                if failure := next(refused, None):
                    raise failure
                return self.answer(*args, **kwargs)

            with (
                mock.patch.object(wikidata, "NEXT_CALL", queue),
                mock.patch.object(Monitor, "waitForAbort", free),
                mock.patch.object(wikidata.http, "get_json", answer),
            ):
                found = wd.details(DUNE, ALIVE)
            self.assertEqual(found["music_by"], ["Hans Zimmer"])

    def test_the_setting(self):
        self.assertEqual(wd.linked(DUNE), {})  # kept only: never asked
        self.assertEqual(self.asked, [])
        wd.details(DUNE, ALIVE)  # as 9000's aside keeps them
        self.setting = False
        self.assertEqual(wd.linked(DUNE), {})
        self.setting = True
        self.asked.clear()
        self.assertEqual(wd.linked(DUNE)["composers"], [ZIMMER])
        self.assertEqual(self.asked, [])
        self.assertEqual(wd.linked(None), {})
        self.assertEqual(wd.video_key("movie", {"tvdb": "1"}), None)
        self.assertEqual(wd.video_key("movie", {"tmdb": "841"}), ("movie", "841", ""))


class ServeTest(WikidataCase):
    """The metadata serve's wikidata=true: kept details only, the rest asked aside."""

    def setUp(self):
        super().setUp()
        self.labels, self.started = {}, []
        thread = lambda target, daemon: mock.Mock(
            start=lambda: self.started.append(target)
        )
        for target, name, value in (
            (cache, "Thread", thread),
            (handlers, "infolabel", lambda label: self.labels.get(label, "")),
            (sys.modules["xbmc"], "executeJSONRPC", self.rpc),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        queue = wd.ASIDES
        self.addCleanup(queue.asked.clear)
        self.addCleanup(queue.queue.clear)
        self.addCleanup(setattr, queue, "running", 0)

    def rpc(self, request):
        request = json.loads(request)
        method = request["method"]
        if method == "AudioLibrary.GetArtistDetails":
            details = {"artistid": 3, "artist": "Daft Punk"}
            details["musicbrainzartistid"] = [DAFT_PUNK]
            return json.dumps({"result": {"artistdetails": details}})
        group = "baf438d5-47ce-399c-9389-40a5d5f14632"
        details = {"albumid": 4, "label": "Dune", "musicbrainzreleasegroupid": group}
        return json.dumps({"result": {"albumdetails": details}})

    def served(self, dbtype, again, **params):
        params |= {"info": "metadata", "target": "item", "type": dbtype, "id": "4"}
        plugin = handlers.PluginHandlers(params | {"wikidata": "true"}, again=again)
        return plugin._wikidata("Dune")

    def test_kept_only_then_aside(self):
        self.labels["ListItem.UniqueID(tmdb)"] = "438631"
        asker = mock.Mock(current=lambda: True)
        self.assertEqual(self.served("movie", None), {})  # a plugin call: kept only
        self.assertEqual((self.asked, self.started), ([], []))
        # none yet: marked pending, for the skin to mask the re-serve
        self.assertEqual(self.served("movie", asker), {"wikidata_pending": "true"})
        self.assertEqual(self.asked, [])  # the serve itself sends nothing
        wd.ASIDES._drain()
        asker.assert_called_once()
        self.assertEqual(
            self.served("movie", asker),
            {
                "wikidata_music_by": "Hans Zimmer",
                "wikidata_based_on": "the novel by Frank Herbert",
                "wikidata_set_in": "Arrakis",
            },
        )
        self.assertEqual(len(self.started), 1)  # fresh: no second ask

    def test_no_id_or_off_asks_nothing(self):
        asker = mock.Mock(current=lambda: True)
        self.assertEqual(self.served("movie", asker), {})  # no TMDb or IMDb id
        self.assertEqual(self.served("episode", asker), {})
        self.setting = False
        self.labels["ListItem.UniqueID(tmdb)"] = "438631"
        self.assertEqual(self.served("movie", asker), {})
        self.assertEqual((self.asked, self.started), ([], []))

    def test_music_by_musicbrainz_id(self):
        wd.details(("artist", DAFT_PUNK), ALIVE)
        wd.details(("album", "baf438d5-47ce-399c-9389-40a5d5f14632"), ALIVE)
        self.assertEqual(
            self.served("artist", None)["wikidata_labels"],
            "Soma Quality Recordings, Virgin Records +2",
        )
        self.assertEqual(self.served("album", None), {"wikidata_producer": "Toto"})

    def test_the_place_fits_beside_the_date(self):
        wd.details(("artist", DAFT_PUNK), ALIVE)
        place = lambda: self.served("artist", None, place_chips="22")["wikidata_place"]
        self.labels["ListItem.Property(artist_formed)"] = "1993"
        self.assertEqual(place(), "Paris")
        self.labels["ListItem.Property(artist_born)"] = "21 March 1974 in a town"
        self.assertEqual(place(), "")  # no room: no chip
        self.labels["ListItem.Property(artist_born)"] = "21st of March 1974"  # 18
        self.assertEqual(place(), "Par…")
        self.assertEqual(self.served("artist", None)["wikidata_place"], "Paris")


class CompilationTest(unittest.TestCase):
    """compilation_artists: a compilation's track artists from the library alone."""

    def setUp(self):
        self.album, self.songs = {}, []

        def rpc(request):
            method = json.loads(request)["method"]
            if method == "AudioLibrary.GetAlbumDetails":
                return json.dumps({"result": {"albumdetails": self.album}})
            return json.dumps({"result": {"songs": self.songs}})

        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (helpers, "get_infolabels", lambda target, keys: dict.fromkeys(keys, "")),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetch(self, **opts):
        handler = helpers.DataHandler("ListItem", "album", "7")
        return handler.fetch_data(**opts)["properties"].get("compilation_artists")

    def test_various_artists(self):
        self.album = {"compilation": False}
        self.album["musicbrainzalbumartistid"] = [helpers.VARIOUS_ARTISTS]
        self.songs = [
            {"artist": ["Travis Scott"]},
            {"artist": ["Glorilla", "Travis Scott"]},
            {"artist": ["Glorilla"]},
            {"artist": ["Glorilla"]},
            *({"artist": [f"Artist {n}"]} for n in range(18)),
        ]
        self.assertIsNone(self.fetch())  # opt-in
        self.assertEqual(
            self.fetch(compilation_artists=True), "Glorilla, Travis Scott +18"
        )

    def test_kodis_flag_and_not_one(self):
        self.album = {"compilation": True, "musicbrainzalbumartistid": [""]}
        self.songs = [{"artist": ["A"]}, {"artist": ["B"]}]
        self.assertEqual(self.fetch(compilation_artists=True), "A, B")
        self.album = {"compilation": False, "musicbrainzalbumartistid": [DAFT_PUNK]}
        self.assertIsNone(self.fetch(compilation_artists=True))
        self.album, self.songs = {"compilation": True}, []
        self.assertIsNone(self.fetch(compilation_artists=True))  # no songs: none


# The library: Dune twice, a film whose album no tag calls a soundtrack, a show
MOVIES = [
    {"movieid": 1, "title": "Dune", "year": 1984, "tmdb": "841", "imdb": "tt0087182"},
    {"movieid": 2, "title": "Dune", "year": 2021, "tmdb": "438631"},
    {"movieid": 3, "title": "Despicable Me 4", "year": 2024, "tmdb": "519182"},
    {"movieid": 4, "title": "The Virgin Suicides", "year": 1999, "tmdb": "1443"},
]
SHOWS = [{"tvshowid": 1, "title": "Westworld", "year": 2016, "tmdb": "63247"}]
ALBUMS = [  # id, title, genre, album artist, release group
    (10, "Dune", ["Soundtrack"], ZIMMER, "rg-unlinked"),  # undated: no year to tell
    (
        11,
        "Despicable Me 4",
        ["Pop"],
        "m-pharrell",
        "9128b04b-fd95-479c-963e-99dcdbf00849",
    ),
    (12, "Dune", ["Rock"], "m-toto", "baf438d5-47ce-399c-9389-40a5d5f14632"),
    (13, "Westworld: Season 2", ["Score"], "m-djawadi", "rg-westworld-2"),
    (
        14,
        "The Virgin Suicides",
        ["Electronic"],
        "m-air",
        "80aa8257-7bc5-39c0-87e1-95941e4c746c",
    ),
    (15, "Discovery", ["Electronic"], DAFT_PUNK, "rg-discovery"),
]


def video_row(type, row):
    """A library film or show as JSON-RPC gives it, with its uniqueid."""
    ids = {name: row[name] for name in ("tmdb", "imdb") if name in row}
    return {
        f"{type}id": row[f"{type}id"],
        "label": row["title"],
        "title": row["title"],
        "originaltitle": "",
        "year": row["year"],
        "uniqueid": ids,
    }


def album_row(albumid, title, genre, artist, group):
    """A library album as JSON-RPC gives it."""
    return {
        "albumid": albumid,
        "label": title,
        "title": title,
        "type": "",
        "genre": genre,
        "style": [],
        "year": 0,
        "originaldate": "",
        "displayartist": "",
        "userrating": 0,
        "art": {},
        "artistid": [1],
        "musicbrainzalbumartistid": [artist],
        "musicbrainzreleasegroupid": group,
    }


def matches(rule, row):
    """Whether a library row passes a JSON-RPC filter rule tree (the rules used)."""
    if "and" in rule or "or" in rule:
        rules = rule.get("and") or rule["or"]
        test = all if "and" in rule else any
        return test(matches(r, row) for r in rules)
    field = {"album": "title", "styles": "style"}.get(rule["field"], rule["field"])
    value, text = rule["value"], row[field]
    texts = text if isinstance(text, list) else [text]
    if rule["operator"] == "is":
        return any(t in value for t in texts)
    if rule["operator"] == "startswith":
        return any(t.startswith(value) for t in texts)
    return any(value in t.casefold() for t in texts)  # contains


class SoundtracksTest(WikidataCase):
    """The soundtracks listing both ways, Kodi's library faked."""

    def setUp(self):
        super().setUp()
        self.entities |= {  # Westworld's show and its season 2 album
            "Q17572811": item("Q17572811", "Westworld", P4983=["63247"], P406=["Q920"]),
            "Q920": item("Q920", "Westworld: Season 2", P436=["rg-westworld-2"]),
        }
        self.library = {
            "movie": [video_row("movie", row) for row in MOVIES],
            "tvshow": [video_row("tvshow", row) for row in SHOWS],
            "album": [album_row(*row) for row in ALBUMS],
        }
        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", self.rpc),
            (handlers, "library_item", lambda album, type: album["albumid"]),
            (handlers, "set_plugincontent", lambda **kwargs: None),
            (
                handlers,
                "build_items",
                lambda rows, type, applier: [
                    (f"{type} {rows[0][f'{type}id']}", mock.Mock(), False)
                ],
            ),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def rpc(self, request):
        request = json.loads(request)
        method, params = request["method"], request["params"]
        kind = next(
            k for k in ("movie", "tvshow", "album", "season") if k in method.lower()
        )
        if kind == "season":
            details = {"seasonid": params["seasonid"], "tvshowid": 1, "season": 1}
            if params["seasonid"] == 2:
                details["season"] = 2
            return json.dumps({"result": {"seasondetails": details}})
        rows = self.library[kind]
        if method.endswith("Details"):
            row = next(r for r in rows if r[f"{kind}id"] == params[f"{kind}id"])
            return json.dumps({"result": {f"{kind}details": row}})
        rule = params.get("filter")
        found = [row for row in rows if not rule or matches(rule, row)]
        return json.dumps({"result": {f"{kind}s": found}})

    def keep(self):
        """Every library item's details kept, as their info screens' 9000 keeps them."""
        for type in ("movie", "tvshow"):
            for row in self.library[type]:
                wd.details(wd.video_key(type, row["uniqueid"]), ALIVE)
        for row in self.library["album"]:
            wd.details(("album", row["musicbrainzreleasegroupid"]), ALIVE)
        self.asked.clear()

    def listing(self, type, dbid):
        params = {"info": "soundtracks", "type": type, "id": str(dbid)}
        found = handlers.PluginHandlers(params).soundtracks()
        self.assertEqual(self.asked, [])  # kept details only: never the network
        return found

    def test_off_title_alone(self):
        self.keep()
        self.setting = False
        self.assertEqual(self.listing("movie", 1), [10])  # undated: the first Dune
        self.assertIsNone(self.listing("movie", 2))
        self.assertIsNone(self.listing("movie", 3))  # no tag says soundtrack
        self.assertEqual(self.listing("album", 10)[0][0], "movie 1")
        self.assertIsNone(self.listing("album", 11))

    def test_none_kept_title_alone(self):
        self.assertEqual(self.listing("movie", 1), [10])
        self.assertIsNone(self.listing("movie", 3))
        self.assertEqual(self.listing("album", 10)[0][0], "movie 1")
        self.assertIsNone(self.listing("album", 11))  # no tag: no title search

    def test_composer_breaks_the_tie(self):
        self.keep()
        self.assertEqual(self.listing("movie", 2), [10])  # Zimmer scored 2021's
        self.assertEqual(self.listing("movie", 1), [12])  # 1984's by its link alone
        self.assertEqual(self.listing("album", 10)[0][0], "movie 2")

    def test_the_id_link_before_the_composer(self):
        # Zimmer's "Dune" album, which Wikidata links to the 1984 film: that one, both
        # ways (by the composer alone, 2021's would list it too)
        link = item("Q114819", "Dune", P406=["Q930"])["claims"]["P406"]
        self.entities["Q114819"]["claims"]["P406"] += link
        self.entities["Q930"] = item("Q930", "Dune", P436=["rg-dune-zimmer"])
        self.library["album"].append(
            album_row(16, "Dune", ["Soundtrack"], ZIMMER, "rg-dune-zimmer")
        )
        self.keep()
        self.assertCountEqual(self.listing("movie", 1), [12, 16])
        self.assertEqual(self.listing("movie", 2), [10])
        self.assertEqual(self.listing("album", 16)[0][0], "movie 1")

    def test_id_link_whatever_the_tags(self):
        self.keep()
        self.assertEqual(self.listing("movie", 3), [11])
        self.assertEqual(self.listing("album", 11)[0][0], "movie 3")
        # the album's own P9899 names the film
        self.assertEqual(self.listing("album", 14)[0][0], "movie 4")
        self.assertIsNone(self.listing("album", 15))  # no link, no tag

    def test_a_season_keeps_its_own(self):
        self.keep()
        self.assertEqual(self.listing("tvshow", 1), [13])
        self.assertEqual(self.listing("season", 2), [13])
        self.assertIsNone(self.listing("season", 1))  # it names season 2

    def test_wikidata_down_title_alone(self):
        self.refuse = HttpError(None)
        self.keep()  # nothing kept
        self.assertEqual(self.listing("movie", 1), [10])
        self.assertIsNone(self.listing("movie", 3))
        self.assertEqual(self.listing("album", 10)[0][0], "movie 1")


if __name__ == "__main__":
    unittest.main()
