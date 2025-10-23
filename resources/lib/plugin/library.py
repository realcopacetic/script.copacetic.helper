# author: realcopacetic

from functools import wraps
from typing import Callable

import xbmc
from xbmcgui import ListItem

_LIST_ATTRS: set[str] = {
    "Directors",
    "Genres",
    "Studios",
    "Writers",
    "Artists",
    "Countries",
    "ShowLinks",
}
_INT_ATTRS: set[str] = {
    "DbId",
    "Playcount",
    "Duration",
    "Year",
    "Episode",
    "Season",
    "Top250",
    "TrackNumber",
}


def _as_list(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def add_items(items: list[dict], media_type: str = "metadata") -> list[tuple]:
    """
    Convert a list of item dicts into Kodi directory items.
    Each dict must include a "file" key and relevant metadata.

    :param items: List of item dicts with at least a "file" key.
    :param media_type: Handler type for setting ListItem properties.
    :return: List of (file, xbmcgui.ListItem, isFolder) tuples.
    """
    li: list[tuple] = []
    type_mapping = {
        "metadata": set_metadata,
        "progressbar": set_progressbar,
        "artwork": set_artwork,
        "movie": set_movie,
        "tvshow": set_tvshow,
        "episode": set_episode,
        "musicvideo": set_musicvideo,
    }
    handler = type_mapping.get(media_type, set_metadata)
    for item in items:
        li_item = handler(item)
        li.append((item["file"], li_item, False))
    return li

def create_li_item(
    item: dict, label: str | None, default_icon: str, properties: dict | None = None
) -> ListItem:
    """
    Creates a Kodi ListItem with basic art and optional properties.

    :param item: Dictionary containing metadata.
    :param label: Display label for the item.
    :param default_icon: Fallback icon if artwork is missing.
    :param properties: Optional dictionary of ListItem properties.
    :returns: xbmcgui.ListItem instance
    """
    li_item = ListItem(label, offscreen=True)
    li_item.setArt({**item.get("art", {}), "icon": default_icon, "thumb": default_icon})

    if properties:
        for key, value in properties.items():
            li_item.setProperty(key, str(value))

    return li_item


def videoinfotag_setter(
    media_type: str, info_mapping: dict, stream_fields: dict | None = None
) -> Callable:
    """
    Decorator that injects video metadata and stream details into ListItem.

    :param media_type: Default media type string, or dynamic fallback.
    :param info_mapping: Dict mapping input keys to VideoInfoTag setters.
    :param stream_fields: Dict mapping stream types to setter functions.
    :returns: Decorator wrapping a ListItem creation function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(item):
            li_item = func(item)
            tag = li_item.getVideoInfoTag()
            tag.setMediaType(media_type or item.get("dbtype"))

            for key, attr in info_mapping.items():
                if key not in item:
                    continue
                value = item[key]
                if value in (None, ""):
                    continue
                setter = getattr(tag, f"set{attr}", None)
                if not setter:
                    continue
                if attr in _LIST_ATTRS:
                    seq = _as_list(value)
                    if seq:
                        setter(seq)
                elif attr in _INT_ATTRS:
                    try:
                        setter(int(value))
                    except (TypeError, ValueError):
                        pass
                else:
                    setter(str(value))

            if isinstance((resume := item.get("resume")), dict):
                tag.setResumePoint(
                    resume.get("position", 0), resume.get("total", 0)
                )

            if stream_fields and "streamdetails" in item:
                for kind, streams in item["streamdetails"].items():
                    if not streams:
                        continue
                    add_method_name = f"add{stream_fields.get(kind, '')}"
                    add = getattr(tag, add_method_name, None)
                    if not add:
                        continue
                    for s in streams:
                        if not isinstance(s, dict):
                            continue
                        if kind == "video":
                            add(xbmc.VideoStreamDetail(**s))
                        elif kind == "audio":
                            add(xbmc.AudioStreamDetail(**s))
                        elif kind == "subtitle":
                            add(xbmc.SubtitleStreamDetail(**s))

            return li_item

        return wrapper

    return decorator


@videoinfotag_setter(
    "",
    {
        "director": "Directors",
        "genre": "Genres",
        "plot": "Plot",
        "studio": "Studios",
        "writer": "Writers",
    },
)
def set_metadata(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for helper service using mapped metadata.

    :param item: Dictionary containing item metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(
        item,
        item.get("label"),
        "DefaultVideo.png",
    )


@videoinfotag_setter("", {})
def set_progressbar(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for progressbar helper using mapped metadata.

    :param item: Dictionary containing item metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(
        item,
        item.get("label"),
        "DefaultVideo.png",
        properties={"unwatchedepisodes": item.get("unwatchedepisodes", "0")},
    )


def set_artwork(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for artwork helper service using mapped artwork.

    :param item: Dictionary containing item metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(
        item,
        item.get("label"),
        "DefaultVideo.png",
    )


@videoinfotag_setter(
    "movie",
    {
        "director": "Directors",
        "lastplayed": "LastPlayed",
        "movieid": "DbId",
        "mpaa": "Mpaa",
        "playcount": "Playcount",
        "plot": "Plot",
        "plotoutline": "PlotOutline",
        "runtime": "Duration",
        "studio": "Studios",
        "tagline": "TagLine",
        "title": "Title",
        "trailer": "Trailer",
        "year": "Year",
    },
    stream_fields={"video": "VideoStream", "audio": "AudioStream"},
)
def set_movie(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for a movie using mapped metadata and artwork.

    :param item: Dictionary containing movie metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(item, item.get("title"), "DefaultMovies.png")


@videoinfotag_setter(
    "tvshow",
    {
        "lastplayed": "LastPlayed",
        "tvshowid": "DbId",
        "mpaa": "Mpaa",
        "plot": "Plot",
        "studio": "Studios",
        "title": "Title",
        "year": "Year",
    },
)
def set_tvshow(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for a tv show using mapped metadata and artwork.

    :param item: Dictionary containing tv show metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    episode = item.get("episode", 0)
    watched_episodes = item.get("watchedepisodes", 0)
    season = item.get("season", 0)

    return create_li_item(
        item,
        item.get("title"),
        "DefaultTVShows.png",
        properties={
            "totalseasons": season,
            "totalepisodes": episode,
            "watchedepisodes": watched_episodes,
            "unwatchedepisodes": max(episode - watched_episodes, 0),
            "watchedepisodepercent": int(
                (watched_episodes / episode * 100) if episode else 0
            ),
        },
    )


@videoinfotag_setter(
    "episode",
    {
        "episode": "Episode",
        "episodeid": "DbId",
        "firstaired": "Premiered",
        "lastplayed": "LastPlayed",
        "mpaa": "Mpaa",
        "playcount": "Playcount",
        "plot": "Plot",
        "runtime": "Duration",
        "season": "Season",
        "showtitle": "TvShowTitle",
        "studio": "Studios",
        "title": "Title",
    },
    stream_fields={"video": "VideoStream", "audio": "AudioStream"},
)
def set_episode(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for an episode using mapped metadata and artwork.

    :param item: Dictionary containing episode metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(
        item,
        f"{item.get('season', 0)}x{item.get('episode', 0):02}",
        "DefaultTVShows.png",
    )


@videoinfotag_setter(
    "musicvideo",
    {
        "artist": "Artists",
        "musicvideoid": "DbId",
        "runtime": "Duration",
        "lastplayed": "LastPlayed",
        "playcount": "Playcount",
        "title": "Title",
        "year": "Year",
    },
    stream_fields={"video": "VideoStream", "audio": "AudioStream"},
)
def set_musicvideo(item: dict) -> ListItem:
    """
    Builds a Kodi ListItem for a music video using mapped metadata and artwork.

    :param item: Dictionary containing music video metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(item, item.get("title"), "DefaultVideo.png")
