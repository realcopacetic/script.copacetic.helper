"""
Offline checks for games (resources/lib/service/games.py, service/player.py): the
emulator read from a game add-on's name as Kodi reads it; the system from the skin's
emulators mapping (one system, several by extension, a shared extension, no row, no
mapping); what a game's start publishes and its stop clears. With a skin's folder,
that skin's own mapping too: its shape, and one emulator of each kind.
Run from the helper root: python tests/games_offline.py [../skin.copacetic2]
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from build_offline import HELPER, install_stubs

SKIN = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else None
STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
LABELS = {}
vars(sys.modules["xbmc"]).update(  # imported names; never called here
    Player=object,
    InfoTagVideo=None,
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    VideoStreamDetail=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    getInfoLabel=lambda label: LABELS.get(label, ""),
)
sys.path.insert(0, str(HELPER))

from resources.lib.service import games, player  # noqa: E402

MAPPING = STAGE / games.EMULATORS
SNES9X, GENPLUS, BSNES = (
    f"game.libretro.{core}" for core in ("snes9x", "genplus", "bsnes")
)
CORES = {
    SNES9X: {"system": "SNES"},
    GENPLUS: {"extensions": {"md": "Mega Drive", "sms": "Master System"}},
    BSNES: {"system": "SNES", "extensions": {"gb": "Game Boy"}},
}
NAMES = {
    SNES9X: "Nintendo - SNES / SFC (Snes9x)",
    GENPLUS: "Sega - MS/GG/MD/CD (Genesis Plus GX)",
    BSNES: "Nintendo - SNES / SFC (bsnes)",
    "game.libretro.2048": "2048",
}


def write_mapping(cores: dict) -> None:
    """Write the skin's emulators mapping with these rows."""
    MAPPING.parent.mkdir(parents=True, exist_ok=True)
    MAPPING.write_text(
        json.dumps({"emulators": {"items": list(cores), "metadata": cores}}),
        encoding="utf-8",
    )


def system(client: str, path: str) -> str:
    """The system identity() gives a file played by a client."""
    return games.identity(client, path)["player_system"]


class Kodi(unittest.TestCase):
    def setUp(self):
        LABELS.clear()
        LABELS.update({f"System.AddonTitle({k})": v for k, v in NAMES.items()})
        write_mapping(CORES)


class EmulatorName(unittest.TestCase):
    def test_the_bracket_names_the_emulator(self):
        self.assertEqual(games.emulator_name(NAMES[SNES9X]), "Snes9x")
        self.assertEqual(games.emulator_name(NAMES[GENPLUS]), "Genesis Plus GX")

    def test_no_bracket_is_the_whole_name(self):
        self.assertEqual(games.emulator_name("2048"), "2048")
        self.assertEqual(games.emulator_name("Odd ) name ("), "Odd ) name (")

    def test_first_bracket_to_first_as_kodi(self):
        name = "Commodore - C64 (VICE x64, fast) (beta)"
        self.assertEqual(games.emulator_name(name), "VICE x64, fast")


class Identity(Kodi):
    def test_one_system(self):
        self.assertEqual(
            games.identity(SNES9X, "/roms/Super Mario World.sfc"),
            {"player_emulator": "Snes9x", "player_system": "SNES"},
        )
        self.assertEqual(system(SNES9X, "/roms/Super Mario World.zip"), "SNES")

    def test_several_systems_by_extension(self):
        self.assertEqual(system(GENPLUS, "/roms/Sonic.md"), "Mega Drive")
        self.assertEqual(system(GENPLUS, "smb://nas/roms/Sonic.SMS"), "Master System")
        packed = "zip://%2froms%2fSonic.zip/Sonic The Hedgehog (v1.1).md"
        self.assertEqual(system(GENPLUS, packed), "Mega Drive")

    def test_shared_extension_is_the_emulator_alone(self):
        for path in ("/roms/Sonic.zip", "/roms/Sonic CD.chd", "/roms/Sonic"):
            self.assertEqual(
                games.identity(GENPLUS, path),
                {"player_emulator": "Genesis Plus GX", "player_system": ""},
            )

    def test_extension_over_the_emulators_system(self):
        self.assertEqual(system(BSNES, "/roms/Tetris.gb"), "Game Boy")
        self.assertEqual(system(BSNES, "/roms/F-Zero.sfc"), "SNES")

    def test_no_row(self):
        self.assertEqual(
            games.identity("game.libretro.2048", ""),
            {"player_emulator": "2048", "player_system": ""},
        )

    def test_skin_without_the_mapping(self):
        MAPPING.unlink()
        self.assertEqual(
            games.identity(SNES9X, "/roms/Super Mario World.sfc"),
            {"player_emulator": "Snes9x", "player_system": ""},
        )


class GameStart(Kodi):
    def setUp(self):
        super().setUp()
        self.home = sys.modules["xbmcgui"].Window(10000)
        self.monitor = monitor = object.__new__(player.PlayerMonitor)
        monitor._landed, monitor._dropped_flight = None, False
        monitor._published = set()
        monitor.isPlayingGame = lambda: True
        monitor.isPlaying = lambda: False  # by the time a stop is handled
        monitor.getPlayingItem = lambda: self.item(GENPLUS)
        LABELS["Player.Filenameandpath"] = "/roms/Sonic.md"

    @staticmethod
    def item(client):
        tag = SimpleNamespace(getGameClient=lambda: client)
        return SimpleNamespace(getGameInfoTag=lambda: tag)

    def props(self):
        keys = ("player_emulator", "player_system")
        return {k: v for k in keys if (v := self.home.getProperty(k))}

    def test_start_publishes_and_stop_clears(self):
        self.monitor.onAVStarted()
        self.assertEqual(
            self.props(),
            {"player_emulator": "Genesis Plus GX", "player_system": "Mega Drive"},
        )
        self.monitor._publish({})
        self.assertEqual(self.props(), {})

    def test_next_game_replaces_the_system(self):
        self.monitor.onAVStarted()
        self.monitor.getPlayingItem = lambda: self.item("game.libretro.2048")
        LABELS["Player.Filenameandpath"] = ""
        self.monitor.onAVStarted()
        self.assertEqual(self.props(), {"player_emulator": "2048"})

    def test_stopped_since_the_start(self):
        def stopped():
            raise RuntimeError("Kodi is not playing any item")

        self.monitor.getPlayingItem = stopped
        self.monitor.onAVStarted()
        self.assertEqual(self.props(), {})


@unittest.skipUnless(SKIN, "no skin folder given")
class SkinMapping(Kodi):
    def setUp(self):
        super().setUp()
        self.text = (SKIN / games.EMULATORS).read_text(encoding="utf-8")
        MAPPING.write_text(self.text, encoding="utf-8")

    def test_shape(self):
        mapping = json.loads(self.text)["emulators"]
        self.assertEqual(mapping["items"], list(mapping["metadata"]))
        for core, row in mapping["metadata"].items():
            with self.subTest(core=core):
                self.assertTrue(row.keys() <= {"system", "extensions"} and row)
                extensions = row.get("extensions", {})
                names = [*extensions.values(), row.get("system", "x")]
                self.assertTrue(all(isinstance(n, str) and n for n in names))
                for extension in extensions:
                    self.assertEqual(extension, extension.lower().lstrip("."))

    def test_one_emulator_of_each_kind(self):
        self.assertTrue(system(SNES9X, "/roms/Super Mario World.sfc"))
        mega, master = (system(GENPLUS, f"/roms/Sonic.{e}") for e in ("md", "sms"))
        self.assertTrue(mega and master and mega != master)
        for shared in ("zip", "bin", "iso", "chd"):
            self.assertEqual(system(GENPLUS, f"/roms/Sonic.{shared}"), "")


if __name__ == "__main__":
    unittest.main()
