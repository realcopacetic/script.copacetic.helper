# author: realcopacetic

from dataclasses import dataclass

FANART_KEYS: tuple[str, ...] = (
    "fanart",
    "tvshow.fanart",
    "artist.fanart",
    "thumb",
)
CLEARLOGO_TYPES: frozenset[str] = frozenset({"movie", "set", "tvshow", "artist"})


@dataclass(frozen=True)
class ArtChoice:
    key: str  # e.g. "fanart" or "tvshow.fanart"
    path: str  # resolved VFS path ("" if none found)


def resolve_fanart(art: dict) -> ArtChoice:
    """
    Return the first existing 'fanart-equivalent' image path.

    :param art: Kodi-style art dict (may include scoped keys like 'tvshow.fanart')
    :returns: ArtChoice(key, path) — both empty if nothing valid found.
    """
    thumb = art.get("thumb")
    fanart = art.get("fanart")
    tv_fanart = art.get("tvshow.fanart")
    if thumb and (not fanart or (tv_fanart and fanart == tv_fanart)):
        return ArtChoice("thumb", thumb)

    for key in FANART_KEYS:
        value = art.get(key)
        if value:
            return ArtChoice(key, value)
        
    return ArtChoice("", "")