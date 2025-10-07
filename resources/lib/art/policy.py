# author: realcopacetic

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtChoice:
    target_key: str  # normalized role to publish under (e.g. "fanart")
    path: str  # resolved VFS path ("" if none found)


ART_KEYS: dict[str, tuple[str, ...]] = {
    "fanart": ("fanart", "tvshow.fanart", "artist.fanart", "thumb"),
    "clearlogo": ("clearlogo", "clearlogo-alt", "clearlogo-billboard"),
}


def resolve_art_type(art: dict, art_type: str) -> ArtChoice:
    """
    Choose the best artwork path for a target art_type using ART_KEYS priority,
    with special episode-friendly fanart heuristic.

    :param art: Kodi-style dict of available art {key: path}
    :param art_type: role to resolve (e.g., "fanart", "clearlogo")
    :return: ArtChoice(target_key=art_type, path=...,)
             Empty path if nothing suitable found.
    """
    keys = ART_KEYS.get(art_type, (art_type,))

    # Episode-friendly heuristic: prefer thumb if fanart mirrors tvshow.fanart
    if art_type == "fanart":
        thumb = art.get("thumb")
        fanart = art.get("fanart")
        tv_fanart = art.get("tvshow.fanart")
        if thumb and (not fanart or (tv_fanart and fanart == tv_fanart)):
            return ArtChoice(target_key="fanart", path=thumb)

    # Return first valid path from priority list (or from art_type itself)
    return ArtChoice(
        target_key=art_type,
        path=next((art[k] for k in keys if art.get(k)), art.get(art_type, "")) or "",
    )
