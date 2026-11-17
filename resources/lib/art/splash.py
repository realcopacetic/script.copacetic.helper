# author: realcopacetic

import filecmp
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import xbmcvfs

from resources.lib.art import policy
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
from resources.lib.shared.logger import ADDON_ID
from resources.lib.shared.utilities import create_dir

# In the master profile's add-on data, for every profile: the login screen runs as the
# master profile, and a skin's splash opens before the service. A skin reads them by
# path: the login screen and splash by profile name, the splash's fallback by name.
SHARED = Path(xbmcvfs.translatePath(f"special://masterprofile/addon_data/{ADDON_ID}/"))
LOGIN_BLURS = SHARED / "login"
SPLASH_BLUR = SHARED / "splash.jpg"
PROFILES = xbmcvfs.translatePath("special://masterprofile/profiles.xml")
UNSAFE = re.compile(r'[\\/:*?"<>|]')  # a name that can't be a file name everywhere


def blur(processor: Callable, url: str) -> str | None:
    """
    An image's background blur at the default radius, through the shared art cache.

    :param processor: An ImageEditor's image_processor.
    :param url: The image's path or URL.
    :return: Path of the blurred file, or None.
    """
    opts = ArtOpts.from_params(
        {"background_url": url, "background_blur": "true"}, "background"
    )
    return processor(
        jobs={"background": policy.ART_PROCESS_MAP["background"]},
        art_opts={"background": opts},
    ).get("background")


def place(source: str, dest: Path) -> None:
    """
    Copy a file over dest unless dest already holds its bytes: a rewritten file
    costs Kodi a recache of the texture.

    :param source: File to copy.
    :param dest: Where the skin reads it.
    """
    if dest.is_file() and filecmp.cmp(source, dest, shallow=False):
        return
    create_dir(f"{dest.parent}/")
    if not xbmcvfs.copy(source, str(dest)):
        log.warning(f"splash → Unable to copy {source} → {dest}")


def bake_profiles() -> None:
    """
    Blur each profile's picture into LOGIN_BLURS by its name, for the login screen
    and the splash after it; a profile gone, renamed or without a picture loses its file.
    """
    from resources.lib.art.editor import ImageEditor

    try:
        profiles = ET.parse(PROFILES).getroot().iter("profile")
    except (OSError, ET.ParseError) as error:
        log.debug(f"splash → No profiles to bake → {error}")
        return
    processor = ImageEditor().image_processor
    keep = set()
    for profile in profiles:
        name, thumb = profile.findtext("name", ""), profile.findtext("thumbnail", "")
        if not (name and thumb) or UNSAFE.search(name):
            continue
        dest = LOGIN_BLURS / f"{name}.jpg"
        keep.add(dest)  # a failed blur keeps the last one
        if blurred := blur(processor, thumb):
            place(blurred, dest)
    for file in LOGIN_BLURS.glob("*.jpg"):
        if file not in keep:
            file.unlink()


def save_splash(processor: Callable, fanart: str) -> bool:
    """
    Blur a slide's fanart into SPLASH_BLUR, the splash's picture at the next start.

    :param processor: An ImageEditor's image_processor.
    :param fanart: The slide's fanart URL.
    :return: Whether it was written.
    """
    if blurred := blur(processor, fanart):
        place(blurred, SPLASH_BLUR)
    return bool(blurred)
