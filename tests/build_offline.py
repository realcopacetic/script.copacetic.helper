"""
Run the helper's builder pipeline outside Kodi against a skin directory.

Kodi modules are replaced by the small stubs below; anything the builders
call that isn't stubbed fails loudly. Outputs never touch the skin.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1]
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def fail(message: str) -> None:
    """Print ``message`` to stderr and exit 2: the harness itself failed."""
    print(message, file=sys.stderr)
    sys.exit(2)


def _module(name: str, **attrs) -> None:
    """Register a stub module under ``name`` with the given attributes."""
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


def install_stubs(
    helper: Path, skin: Path, stage: Path, out: Path, verbose: bool
) -> dict[str, int]:
    """
    Stub ``xbmc*`` modules: special:// paths map to ``stage`` and ``out``,
    logs go to stdout, settings come from the add-on's settings.xml defaults.

    :param helper: Helper add-on root.
    :param skin: Skin root (read for its add-on id only).
    :param stage: Scratch skin root holding templates and generated XML.
    :param out: Directory receiving add-on profile files.
    :param verbose: Print DEBUG lines too.
    :return: Counter dict of log lines per level name.
    """
    addon_id = ET.parse(helper / "addon.xml").getroot().get("id")
    skin_id = ET.parse(skin / "addon.xml").getroot().get("id")
    settings = {
        s.get("id"): s.findtext("default", "")
        for s in ET.parse(helper / "resources" / "settings.xml").iter("setting")
    }
    roots = {
        f"special://profile/addon_data/{addon_id}/": out,
        "special://profile/": out / "profile",
        "special://skin/": stage,
    }
    counts = dict.fromkeys(LEVELS, 0)
    properties = {}

    def translate_path(path: str) -> str:
        prefix = next(p for p in roots if path.startswith(p))
        return str(roots[prefix] / path.removeprefix(prefix))

    def log(message: str, level: int = 0) -> None:
        counts[LEVELS[level]] += 1
        if level or verbose:
            print(f"{LEVELS[level]:7} {message}")

    class Addon:
        def getAddonInfo(self, key: str) -> str:
            return {"id": addon_id, "path": str(helper), "name": addon_id}[key]

        def getSettingBool(self, key: str) -> bool:
            return settings[key] == "true"

    class Window:
        def __init__(self, window_id: int = 10000):
            self._props = properties.setdefault(window_id, {})

        def getProperty(self, key: str) -> str:
            return self._props.get(key, "")

        def setProperty(self, key: str, value: str) -> None:
            self._props[key] = value

        def clearProperty(self, key: str) -> None:
            self._props.pop(key, None)

    _module(
        "xbmc",
        LOGDEBUG=0,
        LOGINFO=1,
        LOGWARNING=2,
        LOGERROR=3,
        PLAYLIST_MUSIC=0,
        PLAYLIST_VIDEO=1,
        PlayList=lambda kind: None,
        log=log,
        getSkinDir=lambda: skin_id,
        getCondVisibility=lambda condition: False,
        getInfoLabel=lambda label: "",
        executebuiltin=lambda action, wait=False: log(f"builtin: {action}"),
    )
    _module("xbmcaddon", Addon=Addon)
    _module(
        "xbmcgui", Dialog=lambda: None, Window=Window, getCurrentWindowId=lambda: 10000
    )
    _module("xbmcvfs", translatePath=translate_path)
    _module(
        "xbmcplugin",
        addSortMethod=None,
        setContent=None,
        setPluginCategory=None,
    )
    return counts


def build(
    skin: Path, out: Path, state: Path | None, helper: Path, verbose: bool
) -> dict[str, int]:
    """
    Build every output for ``skin`` into ``out``: ``16x9/*.xml`` plus
    ``runtime_state.json`` and ``resolver_cache.json``.

    :param skin: Skin root containing ``extras/templates``.
    :param out: Output directory; previous outputs in it are replaced.
    :param state: Runtime state to start from; None seeds defaults.
    :param helper: Helper add-on root to import the builders from.
    :param verbose: Print DEBUG log lines.
    :return: Counter dict of log lines per level name.
    """
    skin, out = skin.resolve(), out.resolve()
    if out.is_relative_to(skin):
        fail(f"refusing to write inside the skin: {out}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "16x9", ignore_errors=True)
    for name in ("runtime_state.json", "resolver_cache.json"):
        (out / name).unlink(missing_ok=True)
    if state:
        shutil.copyfile(state, out / "runtime_state.json")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        templates = Path("extras") / "templates"
        shutil.copytree(skin / templates, stage / templates)
        (stage / "16x9").mkdir()
        counts = install_stubs(helper, skin, stage, out, verbose)
        sys.path.insert(0, str(helper))
        from resources.lib.builders.build_elements import BuildElements

        BuildElements().run()
        shutil.copytree(stage / "16x9", out / "16x9")
    return counts


def build_isolated(
    skin: Path, out: Path, helper: Path = HELPER, state: Path | None = None
) -> str:
    """
    Run this script in a fresh interpreter, since the helper resolves its
    paths at import time; exit 2 if the build fails or logs an error.

    :param skin: Skin root to build.
    :param out: Output directory.
    :param helper: Helper root providing the builders.
    :param state: Optional runtime state to start from.
    :return: The build's closing summary line.
    """
    cmd = [sys.executable, __file__, skin, out, "--helper", helper]
    cmd += ["--state", state] if state else []
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        fail(f"build failed for {skin}:\n{result.stdout}{result.stderr}")
    return result.stdout.rstrip().rpartition("\n")[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("skin", type=Path, help="skin root directory")
    parser.add_argument("out", type=Path, help="output directory")
    parser.add_argument("--state", type=Path, help="runtime_state.json to start from")
    parser.add_argument("--helper", type=Path, default=HELPER, help="helper root")
    parser.add_argument("-v", "--verbose", action="store_true", help="show DEBUG")
    args = parser.parse_args()
    counts = build(args.skin, args.out, args.state, args.helper, args.verbose)
    print(", ".join(f"{n} {level.lower()}" for level, n in counts.items()))
    sys.exit(bool(counts["ERROR"]))


if __name__ == "__main__":
    main()
