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


def resolve_fanart(art: dict, dbtype: str | None = None) -> ArtChoice:
    """
    Return the first existing 'fanart-equivalent' image path.
    Return the first existing 'fanart-equivalent' image path.

     :param art: Kodi-style art dict (may include scoped keys like 'tvshow.fanart')
    :param dbtype: Optional Kodi DBType (e.g., 'episode', 'movie', ...)
     :returns: ArtChoice(key, path) — both empty if nothing valid found.
    """
    db = (dbtype or "")
    if db == "episode" and (v := art.get("thumb")):
        return ArtChoice("thumb", v)

    for key in FANART_KEYS:
        if v := art.get(key):
            return ArtChoice(key, v)

    return ArtChoice("", "")


def supports_clearlogo(dbtype: str | None) -> bool:
    """True if this dbtype should have a clearlogo in library data."""
    return (dbtype or "") in CLEARLOGO_TYPES
