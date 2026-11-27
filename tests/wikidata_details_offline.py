"""
Offline checks for Wikidata details (apis/wikidata.py's having, items and labels;
shared/wikidata_details.py; the metadata serve's wikidata=true and
compilation_artists=true; the soundtracks listing's second pass): items found by
TMDb, IMDb and MusicBrainz ids, never by a query; labels in English, else
multilingual, else any language; Based on from written works only, cut to its line
(based_on_*); the Plot tab's story band (story_*): places, period, subjects,
universe and collection chosen, deduplicated and fitted; the heading's lines
(heading_*); a collection's short name (set_suffix); Music by; a show's creators
where TMDb names none; an artist's labels (+N), place and instruments, and its years
active (years_present); an album's producers; a compilation's track artists from the
library; a served item's details kept, missing ones asked aside; a call with none of
those params given nothing of them; the soundtrack id link both ways and the
composer tie-break, and the title matching alone with the setting off or Wikidata
down.

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
from resources.lib.plugin import handlers, music  # noqa: E402
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
    """
    An item as wbgetentities gives it: an English label, statements by property; a
    value starting + is a time, Q an item, else a string.
    """
    statements = {
        prop: [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "property": prop,
                    "datavalue": (
                        {"value": {"id": value}, "type": "wikibase-entityid"}
                        if value[:1] == "Q"
                        else (
                            {"value": {"time": value, "precision": 9}, "type": "time"}
                            if value[:1] == "+"
                            else {"value": value, "type": "string"}
                        )
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


# A show with creators (P170), set in London
CREATED = {
    "Q920": item("Q920", "Show", P4983=["920"], P170=["Q921", "Q922"], P840=["Q84"]),
    "Q921": item("Q921", "Jane Doe"),
    "Q922": item("Q922", "John Roe"),
}
# Oppenheimer's story, as the 26 Nov coverage fetch found it (wdstory)
OPPENHEIMER = {
    "Q108839994": item(
        "Q108839994",
        "Oppenheimer",
        P4947=["872585"],
        P144=["Q4744748"],
        P840=["Q35794", "Q27832090", "Q61"],
        P2408=["Q6927", "Q362", "Q36561"],
        P921=["Q132537", "Q207066", "Q8016240", "Q650051", "Q127050", "Q7098557"],
    ),
    "Q4744748": item(
        "Q4744748",
        "American Prometheus",
        P31=["Q47461344"],  # written work
        P136=["Q36279"],  # biography
        P50=["Q6347357", "Q45811"],
    ),
    "Q6347357": item("Q6347357", "Kai Bird"),
    "Q45811": item("Q45811", "Martin J. Sherwin"),
    "Q35794": item("Q35794", "University of Cambridge", P31=["Q3354859"], P17=["Q145"]),
    "Q27832090": item("Q27832090", "Project Y", P31=["Q483242"], P17=["Q30"]),
    "Q61": item("Q61", "Washington, D.C.", P31=["Q1093829"], P17=["Q30"]),
    "Q6927": item(
        "Q6927",
        "20th century",
        P31=["Q578"],
        P580=["+1901-01-01T00:00:00Z"],
        P582=["+2000-12-31T00:00:00Z"],
    ),
    "Q362": item(
        "Q362",
        "World War II",
        P31=["Q103495", "Q11514315"],
        P580=["+1939-09-01T00:00:00Z"],
        P582=["+1945-09-02T00:00:00Z"],
    ),
    "Q36561": item(
        "Q36561",
        "1940s",
        P31=["Q39911"],
        P580=["+1940-00-00T00:00:00Z"],
        P582=["+1949-00-00T00:00:00Z"],
    ),
    "Q132537": item("Q132537", "J. Robert Oppenheimer", P31=["Q5"]),
    "Q207066": item("Q207066", "McCarthyism", P31=["Q622454"], P17=["Q30"]),
    "Q8016240": item("Q8016240", "trial"),
    "Q650051": item("Q650051", "nuclear bomb", P31=["Q124078422"]),
    "Q127050": item("Q127050", "Manhattan Project", P31=["Q27665152"]),
    "Q7098557": item("Q7098557", "Oppenheimer security hearing", P31=["Q545861"]),
}
# A Knight of the Seven Kingdoms: a universe (P1434) alone
KNIGHT = {
    "Q120277524": item(
        "Q120277524",
        "A Knight of the Seven Kingdoms",
        P4983=["224372"],
        P1434=["Q2461698"],
    ),
    "Q2461698": item("Q2461698", "World of Ice and Fire", P31=["Q559618"]),
}
# Despicable Me 4's universe (its item is the fixture's)
MINIONS = {"Q131324716": item("Q131324716", "Despicable Me universe")}
DESPICABLE_ME = "Q113373276"


class TenWide:
    """A font whose every character is 10 wide, measured as KodiMetric."""

    @staticmethod
    def getlength(text):
        return 10 * len(text)


class Capitals:
    """A font whose capitals are 20 wide, other characters 10."""

    @staticmethod
    def getlength(text):
        return sum(20 if ch.isupper() else 10 for ch in text)


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
            wd.properties("tvshow", found),
            {"wikidata_based_on": "Slow Horses, novel by Mick Herron"},
        )
        self.assertEqual(found["places"], ["London"])
        # five requests, none a query; the place's classes with the source's
        self.assertEqual(
            self.asked,
            [
                "having P4983=95480",
                "labels|claims Q104880809",
                "having P9899=Q104880809",
                "labels|claims Q108063656|Q84",
                "labels Q24929761",
            ],
        )
        self.asked.clear()
        self.assertEqual(wd.details(SLOW_HORSES, ALIVE), found)  # kept
        self.assertEqual(self.asked, [])

    def test_a_shows_creators(self):
        self.entities |= CREATED
        found = wd.details(("tvshow", "920", ""), ALIVE)
        self.assertEqual(found["created_by"], ["Jane Doe", "John Roe"])
        self.assertEqual(self.asked[-1], "labels Q921|Q922")
        self.assertEqual(
            wd.properties("tvshow", found),
            {"wikidata_created_by": "Jane Doe / John Roe"},
        )
        self.assertNotIn("wikidata_created_by", wd.properties("movie", found))
        del found["created_by"]  # details kept before creators were looked up
        self.assertEqual(wd.properties("tvshow", found), {})

    def test_a_film(self):
        found = wd.details(DUNE, ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        self.assertEqual(found["composers"], [ZIMMER])
        self.assertEqual(found["places"], ["Arrakis"])  # P840
        self.assertEqual(found["soundtracks"], ["6790ad81-5b9c-4362-87c0-6c8e8d3d4100"])
        # the work alone, whatever the film's title
        self.assertEqual(
            wd.properties("movie", found),
            {
                "wikidata_music_by": "Hans Zimmer",
                "wikidata_based_on": "Dune, novel by Frank Herbert",
            },
        )
        # films only: the TV details grid has no Music by cell
        self.assertNotIn("wikidata_music_by", wd.properties("tvshow", found))

    def test_imdb_when_tmdb_finds_none(self):
        found = wd.details(("movie", "999999", "tt1160419"), ALIVE)
        self.assertEqual(found["music_by"], ["Hans Zimmer"])
        self.assertEqual(
            self.asked[:2], ["having P4947=999999", "having P345=tt1160419"]
        )

    def test_no_item(self):
        self.assertEqual(wd.details(("movie", "999999", ""), ALIVE), {})
        self.assertEqual(wd.kept(("movie", "999999", "")), ({}, True))  # kept empty
        self.assertEqual(wd.properties("movie", {}), {})

    def test_written_works_only(self):
        # Backrooms: a web series, then a short story (a literary work in form)
        found = wd.details(("movie", "1083381", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found)["wikidata_based_on"],
            "The Backrooms, short story",  # no author
        )
        # a manga's authors by " and "
        found = wd.details(("movie", "670", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found)["wikidata_based_on"],
            "Old Boy, manga by Garon Tsuchiya and Nobuaki Minegishi",
        )
        # a game, a character and a film are no source
        self.entities |= {
            "Q900": item("Q900", "Game Movie", P4947=["900"], P144=["Q901", "Q902"]),
            "Q901": item("Q901", "The Game", P31=["Q7889"]),  # video game
            "Q902": item("Q902", "The Hero", P31=["Q1114461"]),  # comics character
        }
        found = wd.details(("movie", "900", ""), ALIVE)
        self.assertIsNone(found["source"])
        self.assertEqual(wd.properties("movie", found), {})
        # a novel series is a written work
        self.entities |= {
            "Q904": item("Q904", "Series Movie", P4947=["904"], P144=["Q905"]),
            "Q905": item("Q905", "The Saga", P31=["Q1667921"]),
        }
        found = wd.details(("movie", "904", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found)["wikidata_based_on"],
            "The Saga, novel series",
        )
        # a written work whose genre (P136) is biography
        self.entities |= OPPENHEIMER
        found = wd.details(("movie", "872585", ""), ALIVE)
        self.assertEqual(
            wd.properties("movie", found)["wikidata_based_on"],
            "American Prometheus, biography by Kai Bird and Martin J. Sherwin",
        )

    def test_the_type_word(self):
        self.assertEqual(
            wd._kind({"P31": ["Q7725634"], "P7937": ["Q149537"]}), "novella"
        )
        self.assertEqual(wd._kind({"P31": ["Q14406742"]}), "comic")
        self.assertEqual(wd._kind({"P31": ["Q1667921"]}), "novel series")
        self.assertEqual(wd._kind({"P31": ["Q277759"]}), "book series")
        self.assertEqual(wd._kind({"P31": ["Q7725634"], "P7937": ["Q1"]}), "book")
        # a form outranks a genre, a genre the type
        biography = {"P31": ["Q47461344"], "P136": ["Q36279"]}
        self.assertEqual(wd._kind(biography), "biography")
        self.assertEqual(wd._kind(biography | {"P7937": ["Q8261"]}), "novel")
        source = {"title": "Room", "type": "novel", "authors": []}
        self.assertEqual(wd.based_on(source), "Room, novel")

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
            wd.properties("artist", found),
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
        self.assertEqual(wd.properties("artist", duo), {"wikidata_place": "London"})
        singer = wd.details(("artist", "m-911"), ALIVE)  # born (P19)
        self.assertEqual(
            wd.properties("artist", singer),
            {"wikidata_labels": "Daft Life", "wikidata_place": "Paris"},
        )
        # an unlabelled one of the first two counts in +N
        self.entities |= {
            "Q912": item("Q912", "Trio", P434=["m-912"], P264=["Q913", "Q54860"]),
            "Q913": item("Q913", ""),
        }
        trio = wd.details(("artist", "m-912"), ALIVE)
        self.assertEqual(
            wd.properties("artist", trio), {"wikidata_labels": "Daft Life +1"}
        )
        # neither of the first two labelled: no bare "+N"
        self.entities |= {
            "Q914": item("Q914", "Quartet", P434=["m-914"], P264=["Q913", "Q915"]),
            "Q915": item("Q915", ""),
        }
        quartet = wd.details(("artist", "m-914"), ALIVE)
        self.assertEqual((quartet["labels"], quartet["more"]), ([], 2))
        self.assertEqual(wd.properties("artist", quartet), {})

    def test_the_story_look_up(self):
        # places, periods and subjects asked with the source, in one request; the
        # universe's label with the authors'
        self.entities |= OPPENHEIMER
        found = wd.details(("movie", "872585", ""), ALIVE)
        story = "Q4744748|Q35794|Q27832090|Q61|Q6927|Q362|Q36561"
        subjects = "Q132537|Q207066|Q8016240|Q650051|Q127050|Q7098557"
        self.assertEqual(self.asked[-2], f"labels|claims {story}|{subjects}")
        self.assertEqual(self.asked[-1], "labels Q6347357|Q45811")
        self.assertEqual(found["places"], ["University of Cambridge", "Project Y"])
        self.assertEqual(found["period"], ["World War II", 1939, 1945])
        self.assertEqual(len(found["about"]), 6)
        self.assertEqual(found["universe"], "")
        self.entities |= KNIGHT
        found = wd.details(("tvshow", "224372", ""), ALIVE)
        self.assertEqual(self.asked[-1], "labels Q2461698")
        self.assertEqual(found["universe"], "World of Ice and Fire")
        self.assertEqual((found["places"], found["period"]), ([], []))
        # a franchise (P8345) only without a universe
        self.entities |= {
            "Q930": item("Q930", "Westworld", P4983=["930"], P8345=["Q931"]),
            "Q931": item("Q931", "Westworld"),
            "Q932": item("Q932", "Both", P4983=["932"], P1434=["Q2461698"]),
        }
        self.entities["Q932"]["claims"] |= item("Q", "", P8345=["Q931"])["claims"]
        self.assertEqual(
            wd.details(("tvshow", "930", ""), ALIVE)["universe"], "Westworld"
        )
        found = wd.details(("tvshow", "932", ""), ALIVE)
        self.assertEqual(found["universe"], "World of Ice and Fire")

    def test_artist_instruments(self):
        # Wikidata's labels are lower case: capitalised; NAMES named, the rest counted
        self.entities |= {
            "Q916": item(
                "Q916", "Singer", P434=["m-916"], P1303=["Q6607", "Q17172850", "Q5994"]
            ),
            "Q6607": item("Q6607", "guitar"),
            "Q17172850": item("Q17172850", "voice"),
            "Q5994": item("Q5994", "piano"),
        }
        singer = wd.details(("artist", "m-916"), ALIVE)
        self.assertEqual(self.asked[-1], "labels Q6607|Q17172850")
        self.assertEqual(
            wd.properties("artist", singer),
            {"wikidata_instruments": "Guitar, Voice +1"},
        )
        del singer["instruments"]  # details kept before instruments were looked up
        self.assertEqual(wd.properties("artist", singer), {})

    def test_album_producer_and_films(self):
        found = wd.details(("album", "baf438d5-47ce-399c-9389-40a5d5f14632"), ALIVE)
        self.assertEqual(wd.properties("album", found), {"wikidata_producer": "Toto"})
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

    def served(self, dbtype, again, writers=(), title="Dune", **params):
        params |= {"info": "metadata", "target": "item", "type": dbtype, "id": "4"}
        plugin = handlers.PluginHandlers(params | {"wikidata": "true"}, again=again)
        return plugin._wikidata(title, [*writers])

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
                "wikidata_based_on": "Dune, novel by Frank Herbert",
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
        self.assertEqual(place(), "Paris")  # a group's date is its formation's
        self.labels["ListItem.Property(artist_type)"] = "Person"  # a person's, birth
        self.assertEqual(place(), "")  # no room: no chip
        self.labels["ListItem.Property(artist_born)"] = "21st of March 1974"  # 18
        self.assertEqual(place(), "Par…")
        self.assertEqual(self.served("artist", None)["wikidata_place"], "Paris")

    def test_instruments_are_a_persons(self):
        self.entities |= {
            "Q916": item("Q916", "Singer", P434=["m-916"], P1303=["Q6607"]),
            "Q6607": item("Q6607", "guitar"),
        }
        wd.details(("artist", "m-916"), ALIVE)
        with mock.patch.object(handlers, "artist_identity", lambda *a: ("", "m-916")):
            for kind, served in (
                ("Person", "Guitar"),
                ("character", "Guitar"),
                ("Group", None),
                ("", None),
            ):
                self.labels["ListItem.Property(artist_type)"] = kind
                found = self.served("artist", None).get("wikidata_instruments")
                self.assertEqual(found, served, kind)

    def test_created_by_stands_in_for_tmdbs(self):
        self.entities |= CREATED
        wd.details(("tvshow", "920", ""), ALIVE)
        self.labels["ListItem.UniqueID(tmdb)"] = "920"
        self.assertEqual(
            self.served("tvshow", None)["wikidata_created_by"], "Jane Doe / John Roe"
        )
        # TMDb names the creators: theirs alone
        served = self.served("tvshow", None, writers=["Will Smith"])
        self.assertNotIn("wikidata_created_by", served)

    def test_based_on_fits_its_line(self):
        wd.details(SLOW_HORSES, ALIVE)
        self.labels["ListItem.UniqueID(tmdb)"] = "95480"
        self.labels["ListItem.UniqueID(imdb)"] = "tt5875444"
        served = lambda width: self.served(
            "tvshow", None, based_on_font="description_l", based_on_width=width
        )["wikidata_based_on"]
        # "Slow Horses, novel by Mick Herron" is 330 in TenWide: cut at a word
        with mock.patch.object(handlers, "skin_metric", lambda name: TenWide):
            self.assertEqual(served("330"), "Slow Horses, novel by Mick Herron")
            self.assertEqual(served("329"), "Slow Horses, novel by Mick...")
            self.assertEqual(served(""), "Slow Horses, novel by Mick Herron")
        with mock.patch.object(handlers, "skin_metric", lambda name: None):
            self.assertEqual(served("100"), "Slow Horses, novel by Mick Herron")

    def test_the_story_band(self):
        self.entities |= OPPENHEIMER
        wd.details(("movie", "872585", ""), ALIVE)
        self.labels |= {"ListItem.UniqueID(tmdb)": "872585", "ListItem.Year": "2023"}
        band = {
            "story_chip_font": "meta",
            "story_chip_gap": "15",
            "story_chip_padding": "12",
            "story_gap": "60",
        }
        served = lambda width: self.served(
            "movie", None, title="Oppenheimer", story_width=width, **band
        )
        # in TenWide, a chip 10 a character and 24: Set in 542, About 472 (J. Robert
        # Oppenheimer's isn't named by the title "Oppenheimer"), 60 between
        with mock.patch.object(handlers, "skin_metric", lambda name: TenWide):
            self.assertEqual(
                {k: v for k, v in served("1480").items() if k[-2] == "_"},
                {
                    "wikidata_set_in_1": "University of Cambridge",
                    "wikidata_set_in_2": "Project Y",
                    "wikidata_set_in_3": "World War II",
                    "wikidata_about_1": "J. Robert Oppenheimer",
                    "wikidata_about_2": "McCarthyism",
                    "wikidata_about_3": "trial",
                },
            )
            self.assertNotIn("wikidata_about_3", served("1000"))  # 1074 to 985
            self.assertNotIn("wikidata_about_1", served("600"))
            # a band of more than one chip: no collection
            self.labels["ListItem.Set"] = "Oppenheimer Collection"
            self.assertNotIn("wikidata_part_of_1", served("1480"))
        # no width, or no chip font: no band
        self.assertNotIn("wikidata_set_in_1", served(""))
        with mock.patch.object(handlers, "skin_metric", lambda name: None):
            self.assertNotIn("wikidata_set_in_1", served("1480"))

    def test_part_of_on_a_sparse_band(self):
        # Despicable Me 4: its universe is named by its title, so the band holds its
        # collection alone
        self.entities |= MINIONS
        self.entities[DESPICABLE_ME]["claims"] |= item("Q", "", P1434=["Q131324716"])[
            "claims"
        ]
        found = wd.details(("movie", "519182", ""), ALIVE)
        self.assertEqual(found["universe"], "Despicable Me universe")
        self.labels |= {
            "ListItem.UniqueID(tmdb)": "519182",
            "ListItem.Set": "Despicable Me Collection",
        }
        band = {"story_chip_font": "meta", "story_width": "1480"}
        with mock.patch.object(handlers, "skin_metric", lambda name: TenWide):
            served = self.served("movie", None, title="Despicable Me 4", **band)
            self.assertEqual(served["wikidata_part_of_1"], "Despicable Me Collection")
            self.assertNotIn("wikidata_universe_1", served)
            # another title: its universe, and the collection beside one chip
            served = self.served("movie", None, title="Minions", **band)
            self.assertNotIn("wikidata_universe_1", served)  # the collection names it
            self.labels["ListItem.Set"] = "Illumination"
            served = self.served("movie", None, title="Minions", **band)
            self.assertEqual(served["wikidata_universe_1"], "Despicable Me universe")
            self.assertEqual(served["wikidata_part_of_1"], "Illumination")
            # a show: no collection
            served = self.served("tvshow", None, title="Minions", **band)
            self.assertNotIn("wikidata_part_of_1", served)

    def test_another_skins_call(self):
        # wikidata=true alone: the details, none of the band's, heading's or
        # collection's properties, whatever the item has
        self.entities |= OPPENHEIMER
        wd.details(("movie", "872585", ""), ALIVE)
        self.labels |= {
            "ListItem.UniqueID(tmdb)": "872585",
            "ListItem.Set": "Oppenheimer Collection",
        }
        with mock.patch.object(handlers, "skin_metric", lambda name: TenWide):
            served = self.served("movie", None, title="Oppenheimer")
        self.assertEqual(
            served,
            {
                "wikidata_based_on": (
                    "American Prometheus, biography by Kai Bird and Martin J. Sherwin"
                )
            },
        )

    def test_the_chip_width(self):
        params = {"info": "metadata", "target": "item", "type": "movie", "id": "4"}
        params |= {"story_chip_font": "meta", "story_chip_padding": "12"}
        width = lambda **more: handlers.PluginHandlers(
            params | more, again=None
        )._chip_width("story_chip_")
        with mock.patch.object(handlers, "skin_metric", lambda name: Capitals):
            self.assertEqual(width()("Paris"), 60 + 24)  # as written: upper off
            self.assertEqual(width(story_chip_upper="true")("Paris"), 100 + 24)
            self.assertEqual(
                width(story_chip_upper="true", story_chip_max="100")("Paris"), 100
            )
        with mock.patch.object(handlers, "skin_metric", lambda name: None):
            self.assertIsNone(width())  # no such font

    def test_created_by_while_tmdb_is_asked(self):
        # a show's first serve, TMDb asked aside: Writer is empty, Wikidata's stand
        # in; TMDb's landing serves again with its creators (the skin's grid dips)
        self.entities |= CREATED
        wd.details(("tvshow", "920", ""), ALIVE)
        self.labels["ListItem.UniqueID(tmdb)"] = "920"
        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", lambda request: "{}"),
            (handlers, "set_items", lambda items, **kwargs: items),
            (helpers, "infolabel", lambda path: ""),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {"enrich_with_tmdb": "true", "wikidata": "true"}
        handler.item, handler.dbid, handler.dialog = False, "7", False
        handler.dbtype, handler.target_item, handler.again = "tvshow", "ListItem", None
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        handler._apply_truncated_label = lambda *args, **kwargs: None
        handler._get_tmdb_item = lambda **kwargs: ({}, True)
        (item,) = handler.metadata()
        self.assertEqual(item["properties"]["tmdb_pending"], "true")
        self.assertEqual(
            item["properties"]["wikidata_created_by"], "Jane Doe / John Roe"
        )
        landed = {"Writers": ["Will Smith"], "properties": {}}
        handler._get_tmdb_item = lambda **kwargs: (landed, False)
        (item,) = handler.metadata()
        self.assertEqual(item["Writers"], ["Will Smith"])
        self.assertNotIn("wikidata_created_by", item["properties"])


def kept(**items):
    """Items as items() keeps them, by Q-id: each given as (label, claims)."""
    return {
        qid: wikidata._shape(item(qid, label, **claims))
        for qid, (label, claims) in items.items()
    }


class BandTest(unittest.TestCase):
    """The story band's choices (the coverage fetch's cases) and its fitting."""

    def test_places(self):
        # Coco: Mexico is Santa Cecilia's country; Wikidata's order otherwise
        coco = kept(
            Q96=("Mexico", {"P31": ["Q6256"], "P17": ["Q96"]}),
            Q101=("Land of the Dead", {"P31": ["Q101"]}),
            Q102=("Santa Cecilia Acatitlan", {"P17": ["Q96"]}),
        )
        self.assertEqual(
            wd._places([*coco], coco), ["Land of the Dead", "Santa Cecilia Acatitlan"]
        )
        # Room: a country alone is its own country, not another's
        room = kept(Q16=("Canada", {"P17": ["Q16"]}))
        self.assertEqual(wd._places([*room], room), ["Canada"])
        # 2001: the moon, Jupiter and Africa beside a base and a crater
        odyssey = kept(
            Q5=("Clavius Base", {}),
            Q319=("Jupiter", {"P31": ["Q121750", "Q30014"]}),
            Q15=("Africa", {"P31": ["Q5107"]}),
            Q631696=("Tycho", {"P31": ["Q55818"]}),
        )
        self.assertEqual(wd._places([*odyssey], odyssey), ["Clavius Base", "Tycho"])
        # Elio: Earth alone stays; an unlabelled place is none
        elio = kept(Q2=("Earth", {"P31": ["Q3504248"]}), Q9=("", {}))
        self.assertEqual(wd._places([*elio], elio), ["Earth"])

    def test_period(self):
        found = {
            q: wikidata._shape(OPPENHEIMER[q]) for q in ("Q6927", "Q362", "Q36561")
        }
        self.assertEqual(wd._period([*found], found), ["World War II", 1939, 1945])
        del found["Q362"]  # a decade before a century
        self.assertEqual(wd._period([*found], found), ["1940s", 1940, 1949])
        # years, the first in Wikidata's order; with no end, a decade spans ten
        years = kept(
            Q2062=("1991", {"P31": ["Q3186692"], "P585": ["+1991-01-01T00:00:00Z"]}),
            Q2437=("1981", {"P31": ["Q3186692"], "P585": ["+1981-01-01T00:00:00Z"]}),
            Q39847=("1870s", {"P31": ["Q39911"], "P585": ["+1870-01-01T00:00:00Z"]}),
        )
        self.assertEqual(wd._period([*years], years), ["1991", 1991, 1991])
        self.assertEqual(wd._period(["Q39847"], years), ["1870s", 1870, 1879])
        # a century alone, and a named period with no dates
        alone = kept(Q7015=("18th century", {"P31": ["Q578"]}), Q8=("Regency", {}))
        self.assertEqual(wd._period(["Q7015"], alone), ["18th century", None, None])
        self.assertEqual(wd._period([*alone], alone), ["Regency", None, None])
        self.assertEqual(wd._period([], {}), [])

    def test_subjects(self):
        subjects = kept(
            Q1=("bear", {"P31": ["Q55983715"]}),  # Brave's: organisms by a name
            Q2=("1970s", {"P31": ["Q39911"]}),  # The Virgin Suicides'
            Q3=("suicide", {}),
            Q4=("", {}),
        )
        self.assertEqual(wd._subjects([*subjects], subjects), ["suicide"])

    def chips(self, title="Film", year=0, collection="", **found):
        return wd.story_chips(found, title, year, collection)

    def test_the_period_near_its_release(self):
        # The Thing (1982) in the 1980s, Amélie (2001) in the 1990s: their own time
        for period, year, shown in (
            (["1980s", 1980, 1989], 1982, []),
            (["1990s", 1990, 1999], 2001, []),
            (["1990s", 1990, 1999], 2005, ["1990s"]),
            (["World War II", 1939, 1945], 2023, ["World War II"]),
            (["World War II", 1939, 1945], 0, ["World War II"]),  # no year
            (["Regency", None, None], 1995, ["Regency"]),  # no dates
        ):
            columns = self.chips(year=year, period=period)
            self.assertEqual(columns["period"], shown, (period, year))

    def test_about(self):
        # what the title names goes (Peaky Blinders' gang), word by word; three
        about = ["Peaky Blinders", "art", "crime", "family", "war"]
        columns = self.chips("Peaky Blinders", about=about)
        self.assertEqual(columns["about"], ["art", "crime", "family"])
        self.assertEqual(self.chips("Smart People", about=["art"])["about"], ["art"])

    def test_universe(self):
        for title, collection, universe, shown in (
            ("A Knight of the Seven Kingdoms", "", "World of Ice and Fire", True),
            ("Despicable Me 4", "", "Despicable Me universe", False),  # held
            ("Minions", "Despicable Me Collection", "Despicable Me universe", False),
            ("Westworld", "", "Westworld", False),
            ("Dune", "", "The Dune Saga", False),  # holds the title
            ("Coco", "Pixar Collection", "Universe", True),  # nothing but generic
        ):
            columns = self.chips(title, 0, collection, universe=universe)
            self.assertEqual(columns["universe"], [universe] * shown, title)

    def test_part_of(self):
        # only on a band of one chip or none
        self.assertEqual(self.chips(collection="Set")["part_of"], ["Set"])
        self.assertEqual(
            self.chips(collection="Set", places=["London"])["part_of"], ["Set"]
        )
        both = self.chips(collection="Set", places=["London"], about=["spies"])
        self.assertEqual(both["part_of"], [])
        self.assertEqual(self.chips()["part_of"], [])
        # kept before the band: nothing of it
        self.assertEqual(
            self.chips(),
            {"places": [], "period": [], "about": [], "universe": [], "part_of": []},
        )

    def fit(self, width, **columns):
        chip = lambda name: 10 * len(name) + 24
        empty = dict.fromkeys(("places", "period", "about", "universe", "part_of"), [])
        return wd.fit_band(empty | columns, chip, width, 60, 15)

    def test_the_drop_order(self):
        # chips 10 a character and 24, 15 apart; columns 60 apart. Set in: two
        # places and a period, 254 + 114 + 144 + 30; About 3 x 74 + 30; Universe 104
        band = {
            "places": ["University of Cambridge", "Project Y"],
            "period": ["World War II"],
            "about": ["trial", "crime", "drama"],
            "universe": ["Universe"],
        }
        full = 542 + 60 + 252 + 60 + 104
        self.assertEqual(len(self.fit(full, **band)), 7)
        for name, width, left in (
            ("wikidata_universe_1", full - 1, 6),  # 854 left
            ("wikidata_about_3", 853, 5),  # 765
            ("wikidata_about_2", 764, 4),  # 676
            ("wikidata_about_1", 675, 3),  # 542
            ("wikidata_set_in_3", 541, 2),  # the second place: 413
            ("wikidata_set_in_2", 412, 1),  # the period: 254
        ):
            fitted = self.fit(width, **band)
            self.assertNotIn(name, fitted, width)
            self.assertEqual(len(fitted), left, width)
        self.assertEqual(
            self.fit(412, **band), {"wikidata_set_in_1": "University of Cambridge"}
        )
        self.assertEqual(
            self.fit(542 - 1, **band),
            {
                "wikidata_set_in_1": "University of Cambridge",
                "wikidata_set_in_2": "World War II",
            },
        )
        # the first place stays, however narrow; part_of is never dropped
        self.assertEqual(
            self.fit(10, **band), {"wikidata_set_in_1": "University of Cambridge"}
        )
        self.assertEqual(self.fit(10, part_of=["Set"]), {"wikidata_part_of_1": "Set"})
        self.assertEqual(self.fit(1480), {})


class HeadingTest(unittest.TestCase):
    """heading_lines, set_name and artist_years on the metadata serve."""

    def setUp(self):
        self.labels = {}
        for target, name, value in (
            (handlers, "infolabel", lambda label: self.labels.get(label, "")),
            (handlers, "set_items", lambda items, **kwargs: items),
            (helpers, "infolabel", lambda label: self.labels.get(label, "")),
            (sys.modules["xbmc"], "executeJSONRPC", lambda request: "{}"),
            (handlers, "skin_metric", lambda name: TenWide),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def served(self, dbtype, **params):
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = params
        handler.item, handler.dbid, handler.dialog = False, "7", False
        handler.dbtype, handler.target_item, handler.again = dbtype, "ListItem", None
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        handler._apply_truncated_label = lambda *args, **kwargs: None
        return handler.metadata()[0]["properties"]

    def test_heading_lines(self):
        # 10 a character: the tagline, else the title, in two lines at most
        heading = {"heading_font": "title_wide_xl", "heading_width": "100"}
        self.labels["ListItem.Title"] = "Slow Horses"
        self.assertEqual(self.served("tvshow", **heading)["heading_lines"], "2")
        self.labels["ListItem.Title"] = "Oppenheimer"  # 110: a word wider than a line
        self.assertEqual(self.served("movie", **heading)["heading_lines"], "2")
        self.labels["ListItem.Tagline"] = "The world forever changes."
        self.assertEqual(self.served("movie", **heading)["heading_lines"], "2")
        self.labels["ListItem.Tagline"] = "Short."
        self.assertEqual(self.served("movie", **heading)["heading_lines"], "1")
        self.assertNotIn("heading_lines", self.served("movie"))
        self.assertNotIn("heading_lines", self.served("movie", heading_font="x"))
        with mock.patch.object(handlers, "skin_metric", lambda name: None):
            self.assertNotIn("heading_lines", self.served("movie", **heading))

    def test_set_name(self):
        self.labels["ListItem.Set"] = "Planet of the Apes (Reboot) Collection"
        served = lambda **params: self.served("movie", **params).get("set_name")
        self.assertEqual(served(set_suffix="Collection"), "Planet of the Apes (Reboot)")
        self.assertEqual(served(set_suffix="collection"), "Planet of the Apes (Reboot)")
        self.assertEqual(served(set_suffix="Filmreihe"), self.labels["ListItem.Set"])
        self.assertIsNone(served())  # no suffix asked: none
        self.labels["ListItem.Set"] = "Collection"  # the word alone stays
        self.assertEqual(served(set_suffix="Collection"), "Collection")
        self.labels["ListItem.Set"] = ""
        self.assertIsNone(served(set_suffix="Collection"))

    def test_artist_years(self):
        self.labels |= {
            "ListItem.Property(artist_type)": "Group",
            "ListItem.Property(artist_formed)": "2001-01-01",
            "ListItem.Property(artist_born)": "1997-03-04",
        }
        served = lambda: self.served("artist", years_present="present")["artist_years"]
        self.assertEqual(served(), "2001–present")
        self.labels["ListItem.Property(artist_yearsactive)"] = "1990s / 2000s"
        self.assertEqual(served(), "1990s / 2000s")  # Kodi's own first
        self.assertNotIn("artist_years", self.served("artist"))  # not asked
        self.assertNotIn("artist_years", self.served("movie", years_present="now"))

    def test_another_skins_call(self):
        self.labels |= {
            "ListItem.Title": "Oppenheimer",
            "ListItem.Set": "Oppenheimer Collection",
            "ListItem.Property(artist_formed)": "2001",
        }
        for dbtype in ("movie", "artist"):
            served = self.served(dbtype)
            for name in ("heading_lines", "set_name", "artist_years"):
                self.assertNotIn(name, served)


class YearsTest(unittest.TestCase):
    """artist_years: Kodi's years active, else its dates by the artist's type."""

    def years(self, kind="", present="present", **dates):
        fields = ("yearsactive", "born", "formed", "died", "disbanded")
        artist = dict.fromkeys(fields, "") | {"type": kind} | dates
        return music.artist_years(artist, present)

    def test_by_type(self):
        both = {"born": "1971-08-18", "formed": "1985", "died": "", "disbanded": ""}
        self.assertEqual(self.years("Person", **both), "1971–present")
        self.assertEqual(self.years("character", **both), "1971–present")
        for kind in ("Group", "Orchestra", "Choir", "Other", ""):
            self.assertEqual(self.years(kind, **both), "1985–present", kind)
        # each falls back to the other's dates
        self.assertEqual(self.years("Person", formed="1985"), "1985–present")
        self.assertEqual(self.years("Group", born="1997-03-04"), "1997–present")
        ended = {"formed": "1991", "disbanded": "2008-02-22", "died": "2010"}
        self.assertEqual(self.years("Group", **ended), "1991–2008")
        self.assertEqual(self.years("Person", **ended), "1991–2010")
        self.assertEqual(self.years("Group", "nu", formed="1991"), "1991–nu")

    def test_kodis_own_and_none(self):
        self.assertEqual(self.years(yearsactive="1990s", formed="1991"), "1990s")
        self.assertEqual(self.years("Group", disbanded="2008"), "")  # no start
        self.assertEqual(self.years(formed="in the nineties"), "")


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
