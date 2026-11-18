# author: realcopacetic

import os

from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import TEMPLATES, infolabel, skin_path

# The skin's map of game add-on ids to systems, relative to the skin's folder.
EMULATORS = f"{TEMPLATES}/mappings/mappings_emulators.json"


def emulator_name(addon_name: str) -> str:
    """
    The emulator in a game add-on's name, "Platforms (Emulator)", read as Kodi's
    ParseLibretroName does: first bracket to first; else the whole name.

    :param addon_name: The add-on's name.
    :return: The emulator's name.
    """
    start, end = addon_name.find("("), addon_name.find(")")
    return addon_name[start + 1 : end] if -1 < start < end else addon_name


def identity(client: str, path: str) -> dict[str, str]:
    """
    The game pill's lines: the emulator, and the system the skin's emulators mapping
    gives it, by the file's extension where the emulator plays several.

    :param client: The playing game's add-on id.
    :param path: The playing file.
    :return: player_emulator and player_system; the system empty when unmapped.
    """
    mapping = JSONHandler(skin_path(EMULATORS)).data  # none in a skin without one
    cores = next(iter(mapping.values()))["emulators"]["metadata"] if mapping else {}
    core = cores.get(client, {})
    extension = os.path.splitext(path)[1][1:].lower()
    return {
        "player_emulator": emulator_name(infolabel(f"System.AddonTitle({client})")),
        "player_system": core.get("extensions", {}).get(extension)
        or core.get("system", ""),
    }
