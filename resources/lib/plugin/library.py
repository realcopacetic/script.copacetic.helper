# author: realcopacetic

from typing import Any, Callable, Iterable

import xbmc
from xbmcgui import ListItem

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

TAG_TYPES: dict[str, str] = {
    "Artists": "list",
    "DbId": "int",
    "Directors": "list",
    "Duration": "int",
    "Episode": "int",
    "Genres": "list",
    "LastPlayed": "str",
    "Mpaa": "str",
    "Playcount": "int",
    "Plot": "str",
    "PlotOutline": "str",
    "Premiered": "str",
    "Season": "int",
    "Studios": "list",
    "TagLine": "str",
    "Title": "str",
    "Top250": "int",
    "TrackNumber": "int",
    "Trailer": "str",
    "TvShowTitle": "str",
    "Writers": "list",
    "Year": "int",
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


def add_items(
    items: Iterable[dict],
    media_type: str | None = None,
    tag_applier: TagApplier | None = None,
) -> list[tuple]:
    """
    Build Kodi directory items from canonical metadata dictionaries.
    Each dictionary must include a ``file`` key and may include artwork,
    ListItem properties, VideoInfoTag fields, resume data, and streamdetails.

    :param items: Iterable of canonical item dictionaries.
    :param media_type: Logical media type used for tag assignment.
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
    Artwork and properties are applied directly. InfoTag handling is
    delegated to an optional tag applier function.

    :param item: Canonical metadata dictionary for the item.
    :param media_type: Logical media type to annotate the InfoTag.
    :param tag_applier: Optional function to apply InfoTag fields.
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
    Apply VideoInfoTag fields to a ListItem based on canonical metadata.
    Fields must use the canonical tag names defined in ``TAG_TYPES`` and will
    be coerced to the appropriate Kodi type before calling the matching setter.

    :param li_item: ListItem to update.
    :param item: Canonical metadata dictionary.
    :param media_type: Logical media type to annotate the tag.
    :return: ``None``.
    """
    tag = li_item.getVideoInfoTag()
    tag.setMediaType(str(media_type or item.get("DbType") or ""))

    for key, value in item.items():
        coerce_type = TAG_TYPES.get(key)
        if not coerce_type:
            continue

        setter = getattr(tag, f"set{key}", None)
        if not setter or value in (None, ""):
            continue

        try:
            if coerce_type == "int":
                setter(int(value))
            elif coerce_type == "list":
                setter(_as_list(value))
            else:
                setter(str(value))
        except Exception:
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
                continue