# author: realcopacetic

import os
import re
from pathlib import Path

import xbmcvfs

from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    BLURS,
    TEMPLATES,
    create_dir,
    infolabel,
    skin_path,
)

# The skin's map of game add-on ids to systems, relative to the skin's folder.
EMULATORS = f"{TEMPLATES}/mappings/mappings_emulators.json"
# Kodi's saves, a folder per game file's name: each save with a picture beside it.
SAVES = "special://home/saves/"
BLUR = "game_"  # the blur's file name in BLURS, before its picture's time
BLUR_OPTS = ArtOpts.from_params({"background_blur": "true"}, "background")


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


def autosave_blur(editor: ImageEditor, path: str) -> str:
    """
    Blur a game's newest save picture (Kodi autosaves every 10 s of play) into a
    file named by the picture's time: Kodi won't reread a rewritten path.

    :param editor: The artwork editor, for its processor.
    :param path: The playing game's file.
    :return: The blur's path; empty with no picture, or one that can't be read.
    """
    folder = Path(xbmcvfs.translatePath(SAVES), re.split(r"[/\\]", path)[-1])
    try:
        newest = max(folder.glob("*.jpg"), key=os.path.getmtime, default=None)
        if not newest:
            return ""
        stamp = newest.stat().st_mtime_ns
    except OSError:  # Kodi replaced a picture between the listing and the read
        return ""
    blur = Path(BLURS, f"{BLUR}{stamp}.jpg")
    if blur.exists():  # the OSD opened again before the next autosave
        return str(blur)
    from PIL import Image  # a new picture only

    from resources.lib.art.io import write_image
    from resources.lib.script.library import remove_textures

    try:
        with Image.open(newest) as image:
            blurred = editor.processor.blur(image, opts=BLUR_OPTS)
    except OSError:  # Kodi is still writing it
        return ""
    if not blurred:
        return ""
    stale = [str(old) for old in Path(BLURS).glob(f"{BLUR}*.jpg")]
    for old in stale:
        os.remove(old)
    remove_textures(stale)  # Kodi's cached copies of them
    create_dir(BLURS)
    write_image(str(blur), blurred["image"], "JPEG", editor.cfg)
    return str(blur)
