# author: realcopacetic

from typing import Any, Callable, Iterable

import xbmc
from xbmcgui import ListItem
from resources.lib.shared import logger as log

TagApplier = Callable[[ListItem, dict, str | None], None]

_DEFAULT_ICONS: dict[str, str] = {
    "movie": "DefaultMovies.png",
    "tvshow": "DefaultTVShows.png",
    "episode": "DefaultTVShows.png",
    "musicvideo": "DefaultVideo.png",
}

_STREAM_DETAIL_MAP = {
    "video": ("VideoStream", xbmc.VideoStreamDetail),
    "audio": ("AudioStream", xbmc.AudioStreamDetail),
    "subtitle": ("SubtitleStream", xbmc.SubtitleStreamDetail),
}

# Maps canonical ListItem/VideoInfoTag names to their value type and the
# corresponding JSON-RPC source field. Used both by apply_videoinfotag (for
# setter dispatch and type coercion) and by json_to_canonical (via the
# _JSON_TO_CANONICAL reverse lookup) to translate raw JSON-RPC responses
# into canonical metadata. ``json: None`` indicates the value is set by
# other means (e.g. DbId from the response's *id field).
TAG_TYPES: dict[str, dict[str, str | None]] = {
    "Album": {"type": "str", "json": "album"},
    "Artists": {"type": "list", "json": "artist"},
    "Country": {"type": "list", "json": "country"},
    "DateAdded": {"type": "str", "json": "dateadded"},
    "DbId": {"type": "int", "json": None},
    "Directors": {"type": "list", "json": "director"},
    "Duration": {"type": "int", "json": "runtime"},
    "Episode": {"type": "int", "json": "episode"},
    "FirstAired": {"type": "str", "json": "firstaired"},
    "Genres": {"type": "list", "json": "genre"},
    "LastPlayed": {"type": "str", "json": "lastplayed"},
    "Mpaa": {"type": "str", "json": "mpaa"},
    "OriginalTitle": {"type": "str", "json": "originaltitle"},
    "Playcount": {"type": "int", "json": "playcount"},
    "Plot": {"type": "str", "json": "plot"},
    "PlotOutline": {"type": "str", "json": "plotoutline"},
    "Premiered": {"type": "str", "json": "premiered"},
    "ProductionCode": {"type": "str", "json": "productioncode"},
    "Rating": {"type": "str", "json": "rating"},
    "Season": {"type": "int", "json": "season"},
    "Set": {"type": "str", "json": "set"},
    "SetId": {"type": "int", "json": "setid"},
    "SortTitle": {"type": "str", "json": "sorttitle"},
    "Studios": {"type": "list", "json": "studio"},
    "TagLine": {"type": "str", "json": "tagline"},
    "Title": {"type": "str", "json": "title"},
    "Top250": {"type": "int", "json": "top250"},
    "TrackNumber": {"type": "int", "json": "track"},
    "Trailer": {"type": "str", "json": "trailer"},
    "TvShowTitle": {"type": "str", "json": "showtitle"},
    "UserRating": {"type": "int", "json": "userrating"},
    "Votes": {"type": "str", "json": "votes"},
    "Writers": {"type": "list", "json": "writer"},
    "Year": {"type": "int", "json": "year"},
}


def _as_list(value: Any) -> list[str]:
    """
    Normalise a value into a list of non-empty strings.

    :param value: Input value that may be scalar or sequence.
    :return: List of non-empty string values.
    """
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def set_items(
    items: Iterable[dict],
    media_type: str | None = None,
    tag_applier: TagApplier | None = None,
) -> list[tuple]:
    """
    Build directory items from canonical metadata dictionaries.

    :param items: Iterable of canonical item dictionaries.
    :param media_type: Logical media type used for VideoInfoTag assignment.
    :param tag_applier: Optional function to apply VideoInfoTag fields.
    :return: List of ``(file, ListItem, is_folder)`` tuples.
    """
    return [
        (
            item["file"],
            build_listitem(item, media_type=media_type, tag_applier=tag_applier),
            False,
        )
        for item in items
    ]


def build_listitem(
    item: dict,
    media_type: str | None,
    tag_applier: TagApplier | None = None,
) -> ListItem:
    """
    Construct a ListItem from a canonical metadata dictionary.

    :param item: Canonical metadata dictionary for the item.
    :param media_type: Logical media type to annotate the VideoInfoTag.
    :param tag_applier: Optional function to apply VideoInfoTag fields.
    :return: Fully configured ``xbmcgui.ListItem`` instance.
    """
    li = ListItem(
        label=item.get("label", ""),
        label2=item.get("label2", ""),
        offscreen=True,
    )
    art = dict(item.get("art", {}))
    fallback = _DEFAULT_ICONS.get(media_type or "", "DefaultCopacetic.png")
    art.setdefault("icon", fallback)
    art.setdefault("thumb", fallback)
    li.setArt(art)

    for key, value in (item.get("properties") or {}).items():
        li.setProperty(key, str(value))

    if tag_applier is not None:
        tag_applier(li, item, media_type)

    return li


def apply_videoinfotag(
    li_item: ListItem,
    item: dict,
    media_type: str | None,
) -> None:
    """
    Apply VideoInfoTag fields to a ListItem from canonical metadata.

    :param li_item: ListItem to update.
    :param item: Canonical metadata dictionary keyed by tag names.
    :param media_type: Logical media type to annotate the VideoInfoTag.
    :return: ``None``.
    """
    tag = li_item.getVideoInfoTag()
    tag.setMediaType(str(media_type or item.get("DbType") or ""))

    for key, value in item.items():
        spec = TAG_TYPES.get(key)
        coerce_type = spec.get("type") if spec else None
        if not coerce_type:
            continue

        setter = getattr(tag, f"set{key}", None)
        if not setter:
            log.debug(
                f"apply_videoinfotag: no set{key} method on InfoTagVideo; "
                f"TAG_TYPES entry exists but is unreachable."
            )
            continue

        if value in (None, ""):
            continue

        try:
            if coerce_type == "int":
                setter(int(value))
            elif coerce_type == "list":
                setter(_as_list(value))
            else:
                setter(str(value))
        except Exception:
            log.debug(
                f"apply_videoinfotag: Failed to set {key}={value!r} "
                f"(type={coerce_type})"
            )
            continue

    resume = item.get("resume")
    if isinstance(resume, dict):
        tag.setResumePoint(resume.get("position", 0), resume.get("total", 0))

    streamdetails = item.get("streamdetails")
    if not isinstance(streamdetails, dict):
        return

    for kind, streams in streamdetails.items():
        if not streams:
            continue

        method_suffix, detail_cls = _STREAM_DETAIL_MAP.get(kind, (None, None))
        if not method_suffix:
            continue

        add_method = getattr(tag, f"add{method_suffix}", None)
        if not add_method:
            continue

        for s in streams:
            if not isinstance(s, dict):
                continue
            try:
                add_method(detail_cls(**s))
            except TypeError:
                log.debug(f"apply_videoinfotag: Bad {kind} stream detail: {s!r}")
                continue
