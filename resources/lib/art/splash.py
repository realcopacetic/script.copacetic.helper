# author: realcopacetic

import filecmp
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import xbmc
import xbmcvfs

from resources.lib.art import policy
from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
from resources.lib.shared.logger import ADDON_ID
from resources.lib.shared.utilities import create_dir

# In the master profile's add-on data, for every profile: the login screen runs as the
# master profile, and a skin's splash opens before the service. A skin reads them by
# these paths: the login screen and splash by profile name, the splash's fallback.
SHARED = f"special://masterprofile/addon_data/{ADDON_ID}/"
LOGIN_BLURS = f"{SHARED}login/"
SPLASH_BLUR = f"{SHARED}splash.jpg"
PROFILES = "special://masterprofile/profiles.xml"
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


def place(source: str, dest: str) -> bool | None:
    """
    Copy a file over dest unless dest already holds its bytes.

    :param source: File to copy.
    :param dest: Where the skin reads it, as the skin names it.
    :return: True when written, None when dest already held it, False on failure.
    """
    path = Path(xbmcvfs.translatePath(dest))
    if path.is_file() and filecmp.cmp(source, path, shallow=False):
        return None
    create_dir(f"{path.parent}/")
    if not xbmcvfs.copy(source, str(path)):
        log.warning(f"splash → Unable to copy {source} → {dest}")
        return False
    return True


def refresh(urls: list[str]) -> None:
    """
    Drop this profile's cached copies of rewritten or removed files: Kodi rechecks
    a cached image's file at most once a day (CTextureDatabase::GetCachedTexture).

    :param urls: The files as the skin names them.
    """
    if urls:
        from resources.lib.script.library import remove_textures

        remove_textures(urls)


def bake_profiles() -> None:
    """
    Blur each profile's picture into LOGIN_BLURS by its name, for the login screen
    and the splash after it; a profile gone, renamed or without a picture loses its
    file. Stops when Kodi exits.
    """
    try:
        profiles = ET.parse(xbmcvfs.translatePath(PROFILES)).getroot().iter("profile")
    except (OSError, ET.ParseError) as error:
        log.debug(f"splash → No profiles to bake → {error}")
        return
    processor, monitor = ImageEditor().image_processor, xbmc.Monitor()
    keep, changed = set(), []
    for profile in profiles:
        if monitor.abortRequested():
            return
        name = " ".join(profile.findtext("name", "").split())  # as Kodi's XML reader
        thumb = profile.findtext("thumbnail", "")
        if not (name and thumb) or UNSAFE.search(name):
            continue
        dest = f"{LOGIN_BLURS}{name}.jpg"
        keep.add(dest)  # a failed blur keeps the last one
        if (blurred := blur(processor, thumb)) and place(blurred, dest):
            changed.append(dest)
    for file in Path(xbmcvfs.translatePath(LOGIN_BLURS)).glob("*.jpg"):
        if (url := f"{LOGIN_BLURS}{file.name}") not in keep:
            file.unlink()
            changed.append(url)
    refresh(changed)


def save_splash(processor: Callable, fanart: str) -> bool:
    """
    Blur a slide's fanart into SPLASH_BLUR, the splash's picture at the next start.

    :param processor: An ImageEditor's image_processor.
    :param fanart: The slide's fanart URL.
    :return: Whether SPLASH_BLUR holds it.
    """
    if not (blurred := blur(processor, fanart)):
        return False
    if written := place(blurred, SPLASH_BLUR):
        refresh([SPLASH_BLUR])
    return written is not False
