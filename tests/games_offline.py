"""
Offline checks for games (resources/lib/service/games.py, service/player.py): the
emulator read from a game add-on's name as Kodi reads it; the system from the skin's
emulators mapping (one system, several by extension, a shared extension, no row, no
mapping); what a game's start publishes and its stop clears; the autosave blur (the
newest save picture, one file per picture, the last one dropped, none without a
readable picture; needs Pillow) and the poller hook that publishes it once per
opening of the game OSD; the content browser's Game add-ons source
(windows/browse.py). With a skin's folder, that skin's own mapping too: its shape,
and one emulator of each kind.
Run from the helper root: python tests/games_offline.py [../skin.copacetic2]
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from build_offline import HELPER, install_stubs

SKIN = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else None
STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
LABELS, CONDITIONS = {}, set()
vars(sys.modules["xbmc"]).update(  # imported names; never called here
    Player=object,
    InfoTagVideo=None,
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=str,  # a string is its id
    VideoStreamDetail=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    getInfoLabel=lambda label: LABELS.get(label, ""),
    getCondVisibility=lambda condition: condition in CONDITIONS,
)
vfs = sys.modules["xbmcvfs"]
HOME, skin_or_profile = "special://home/", vfs.translatePath
vars(vfs).update(
    File=open,
    mkdirs=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or True,
    translatePath=lambda path: (
        str(STAGE / "home" / path.removeprefix(HOME))
        if path.startswith(HOME)
        else skin_or_profile(path)
    ),
)
sys.modules["xbmcgui"].DialogProgress = None
sys.path.insert(0, str(HELPER))

from resources.lib.script import library  # noqa: E402
from resources.lib.service import games, player  # noqa: E402
from resources.lib.windows import browse  # noqa: E402

MAPPING = STAGE / games.EMULATORS
OSD = "Window.IsActive(gameosd)"
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

    def test_row_with_both_reads_the_extension_first(self):
        # No row of the skin's needs both; the order is the reader's, pinned here
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
        keys = ("player_emulator", "player_system", "player_game_blur")
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

    def poll(self, osd_open, blur="/blur/game_1.jpg"):
        CONDITIONS.clear()
        CONDITIONS.update({OSD} if osd_open else ())
        self.monitor._image_editor = "editor"
        with patch.object(games, "autosave_blur", return_value=blur) as blurred:
            self.monitor.watch_game_osd()
        return blurred.call_args_list

    def test_blur_once_per_osd_opening(self):
        self.monitor._game_osd = False
        self.monitor.onAVStarted()
        self.assertEqual(self.poll(False), [])
        self.assertEqual(self.poll(True)[0].args, ("editor", "/roms/Sonic.md"))
        self.assertEqual(self.props()["player_game_blur"], "/blur/game_1.jpg")
        self.assertEqual(self.poll(True), [])  # still open
        self.assertEqual(self.poll(False), [])
        self.assertNotIn("player_game_blur", self.props())  # closed: cleared
        self.assertEqual(len(self.poll(True, "/blur/game_2.jpg")), 1)
        self.assertEqual(self.props()["player_game_blur"], "/blur/game_2.jpg")

    def test_osd_up_at_the_start_opens_for_this_game(self):
        self.monitor.onAVStarted()
        self.poll(True)
        self.monitor._successor = "/tv/next episode.mkv"
        self.monitor.onAVStarted()  # the next game, Kodi's OSD still up
        self.assertEqual(self.monitor._successor, "")
        self.assertEqual(len(self.poll(True, "/blur/game_2.jpg")), 1)
        self.assertEqual(self.props()["player_game_blur"], "/blur/game_2.jpg")

    def test_game_inside_a_trailers_wait_is_not_sent_full_screen(self):
        self.monitor._dropped_flight = True
        self.monitor.isPlayingVideo = lambda: True  # RetroPlayer has video too
        with patch.object(player.log, "execute") as execute:
            self.monitor.onAVStarted()
        execute.assert_not_called()
        self.assertFalse(self.monitor._dropped_flight)

    def test_no_autosave_sets_nothing_and_a_stop_or_new_game_clears(self):
        self.monitor._game_osd = False
        self.monitor.onAVStarted()
        self.poll(True, "")
        self.assertNotIn("player_game_blur", self.props())
        self.poll(False)
        self.poll(True)
        self.monitor.onAVStarted()  # the next game
        self.assertNotIn("player_game_blur", self.props())
        self.poll(False)
        self.poll(True)
        self.monitor._publish({})
        self.assertEqual(self.props(), {})


class GamesSource(unittest.TestCase):
    PATH = "addons://sources/game"

    def test_listed_with_the_add_on_sources(self):
        with patch.object(browse, "_L", str):
            self.assertEqual(browse._get_addon_sources()[-1], ("35049", self.PATH))

    def test_opens_in_the_games_window(self):
        widget = browse._build_result(self.PATH, "Game add-ons", "widget")
        self.assertEqual(
            widget,
            {
                "path": self.PATH,
                "label": "Game add-ons",
                "icon": "DefaultAddonGame.png",
                "target": "games",
            },
        )
        menu = browse._build_result(self.PATH, "Game add-ons", "menu")
        self.assertEqual(menu["action"], f'ActivateWindow(Games,"{self.PATH}",return)')
        self.assertEqual((menu["type"], menu["window"]), ("games", "Games"))

    def picked(self, source, mode, path="plugin://plugin.program.iagl/"):
        """What the browser returns for a path picked under an add-on source."""
        with (
            patch.object(browse, "_L", str),
            patch.object(browse, "_browse_level", return_value=(path, "IAGL")),
            patch.object(browse, "Dialog") as dialog,
        ):
            dialog.return_value.select.side_effect = [4, source]  # Add-ons, source
            return browse.browse_content({"mode": mode})

    def test_a_plugin_picked_under_a_source_opens_in_its_window(self):
        game, video = 5, 1
        self.assertEqual(self.picked(game, "widget")["target"], "games")
        menu = self.picked(game, "menu")
        self.assertEqual(
            (menu["type"], menu["window"], menu["icon"], menu["action"]),
            (
                "games",
                "Games",
                "DefaultAddonGame.png",
                'ActivateWindow(Games,"plugin://plugin.program.iagl/",return)',
            ),
        )
        # Each add-on source's picks open in the window Kodi lists them in
        windows = [self.picked(i, "menu")["window"] for i in range(1, 5)]
        self.assertEqual(windows, ["Videos", "Music", "Programs", "Pictures"])
        self.assertEqual(self.picked(video, "menu")["icon"], "DefaultVideo.png")

    def test_a_library_path_keeps_its_own_window(self):
        program, movie = 3, "videodb://movies/titles/5/"
        menu = self.picked(program, "menu", movie)
        self.assertEqual(
            (menu["type"], menu["window"], menu["icon"]),
            ("movies", "Videos", "DefaultMovies.png"),
        )

    def test_standalone_game_plays_from_a_menu_item(self):
        game = "game://game.libretro.2048"
        self.assertEqual(
            browse._build_result(game, "2048", "menu"),
            {
                "path": game,
                "label": "2048",
                "icon": "DefaultAddonGame.png",
                "type": "command",
                "window": "",
                "action": f'PlayMedia("{game}")',
                "update": "",
            },
        )

    def test_script_runs_from_a_menu_item(self):
        menu = browse._build_result("script://script.foo", "Foo", "menu")
        self.assertEqual(
            (menu["type"], menu["icon"], menu["action"]),
            ("command", "DefaultAddonProgram.png", 'RunScript("script.foo")'),
        )

    def offered(self, mode):
        """The rows the source's picker lists in a mode."""
        rows = [
            {"file": "plugin://plugin.program.iagl/", "filetype": "directory"},
            {"file": "game://game.libretro.2048", "filetype": "file"},
            {"file": "script://script.foo", "filetype": "file"},
        ]
        rows = [row | {"label": row["file"]} for row in rows]
        with (
            patch.object(browse, "_L", str),
            patch.object(browse, "_get_directory", return_value=rows),
            patch.object(browse, "Dialog") as dialog,
        ):
            dialog.return_value.select.return_value = -1
            browse._browse_level(self.PATH, "Game add-ons", mode)
        return dialog.return_value.select.call_args.args[1][2:]  # after .. and Use

    def test_widget_is_not_offered_a_standalone_game_or_script(self):
        self.assertEqual(self.offered("widget"), ["plugin://plugin.program.iagl/  >"])
        self.assertEqual(
            self.offered("menu"),
            [
                "plugin://plugin.program.iagl/  >",
                "game://game.libretro.2048",
                "script://script.foo",
            ],
        )


@unittest.skipUnless(importlib.util.find_spec("PIL"), "needs Pillow")
class AutosaveBlur(unittest.TestCase):
    def setUp(self):
        from resources.lib.art import policy
        from resources.lib.art.processor import ImageProcessor

        cfg = policy.ColorConfig()
        self.editor = SimpleNamespace(processor=ImageProcessor(cfg), cfg=cfg)
        (STAGE / "home").mkdir(exist_ok=True)
        self.saves = Path(tempfile.mkdtemp(dir=STAGE / "home"))
        self.blurs = Path(tempfile.mkdtemp(dir=STAGE))
        self.removed = []
        for target, name, value in (
            (games, "SAVES", f"{HOME}{self.saves.name}/"),
            (games, "BLURS", str(self.blurs)),
            (library, "remove_textures", self.removed.append),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, colour, at, game="Sonic.md", name="save"):
        """A save picture of one colour, written at a time."""
        from PIL import Image

        shot = self.saves / game / f"{name}.jpg"
        shot.parent.mkdir(exist_ok=True)
        Image.new("RGB", (640, 480), colour).save(shot)
        os.utime(shot, ns=(at, at))
        return shot

    def blur(self, path="/roms/Sonic.md"):
        return games.autosave_blur(self.editor, path)

    def test_no_saves(self):
        self.assertEqual(self.blur(), "")
        self.save("red", 5, game="Other.md")
        self.assertEqual(self.blur(), "")
        self.assertEqual(list(self.blurs.iterdir()), [])

    def test_newest_picture_blurred_by_its_time(self):
        from PIL import Image

        self.save("red", 1_000_000_000, name="manual")
        self.save("blue", 2_000_000_000, name="autosave")
        blur = self.blur()
        self.assertEqual(blur, str(self.blurs / "game_2000000000.jpg"))
        with Image.open(blur) as image:
            red, _, blue = image.convert("RGB").getpixel((10, 10))
            self.assertEqual(image.size, (480, 360))  # covers the 480x270 blur box
        self.assertTrue(blue > 200 > 50 > red)

    def test_same_picture_is_not_blurred_again(self):
        self.save("blue", 2_000_000_000)
        first = self.blur()
        written = Path(first).stat().st_mtime_ns
        with patch.object(self.editor.processor, "blur") as processed:
            self.assertEqual(self.blur(), first)
        processed.assert_not_called()
        self.assertEqual(Path(first).stat().st_mtime_ns, written)

    def test_next_autosave_drops_the_last_blur(self):
        self.save("red", 1_000_000_000)
        first = self.blur()
        self.save("blue", 3_000_000_000)  # the autosave slot, rewritten
        second = self.blur()
        self.assertEqual(
            [p.name for p in self.blurs.iterdir()], ["game_3000000000.jpg"]
        )
        self.assertEqual(second, str(self.blurs / "game_3000000000.jpg"))
        self.assertEqual(self.removed, [[], [first]])

    def test_game_named_by_its_file_as_kodi(self):
        self.save("blue", 4_000_000_000)
        for path in (
            "zip://%2froms%2fSonic.zip/Sonic.md",
            "C:\\roms\\Sonic.md",
            "smb://nas/roms/Sonic.md",
        ):
            self.assertTrue(self.blur(path).endswith("game_4000000000.jpg"))

    def test_picture_still_being_written(self):
        shot = self.save("blue", 5_000_000_000)
        whole = shot.read_bytes()
        for part in (b"", whole[: len(whole) // 2]):
            shot.write_bytes(part)
            with patch.object(player.log, "error"):  # the processor's own
                self.assertEqual(self.blur(), "")
        self.assertEqual(list(self.blurs.iterdir()), [])


@unittest.skipUnless(SKIN, "no skin folder given")
class SkinMapping(Kodi):
    def setUp(self):
        super().setUp()
        if not (SKIN / games.EMULATORS).exists():
            self.skipTest("this skin has no emulators mapping")
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
