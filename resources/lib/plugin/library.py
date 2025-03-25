# author: realcopacetic

from functools import wraps

import xbmc
from xbmcgui import ListItem


def add_items(li, items, media_type="helper"):
    """
    Appends a list of file-based ListItems to a Kodi list container.

    :param li: The Kodi list container (e.g., a directory).
    :param items: List of item dictionaries with metadata.
    :param media_type: Media type used to determine handler function.
    :returns: None
    """
    type_mapping = {
        "helper": set_helper,
        "movie": set_movie,
        "tvshow": set_tvshow,
        "episode": set_episode,
        "musicvideo": set_musicvideo,
    }
    handler = type_mapping.get(media_type, set_helper)
    for item in items:
        li_item = handler(item)
        li.append((item["file"], li_item, False))


def create_li_item(item, label, default_icon, properties=None):
    """
    Creates a Kodi ListItem with basic art and optional properties.

    :param item: Dictionary containing artwork and other metadata.
    :param label: Display label for the item.
    :param default_icon: Fallback icon if artwork is missing.
    :param properties: Optional dictionary of ListItem properties.
    :returns: xbmcgui.ListItem instance
    """
    li_item = ListItem(label, offscreen=True)
    li_item.setArt({**item.get("art", {}), "icon": default_icon})

    if properties:
        for key, value in properties.items():
            li_item.setProperty(key, str(value))

    return li_item


def videoinfotag_setter(media_type, info_mapping, stream_fields=None):
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
            video_info = li_item.getVideoInfoTag()
            video_info.setMediaType(media_type or item.get("dbtype"))

            for key, attr in info_mapping.items():
                if value := item.get(key):
                    getattr(video_info, f"set{attr}")(
                        value if isinstance(value, list) else [value]
                    )

            if resume := item.get("resume", {}):
                video_info.setResumePoint(
                    resume.get("position", 0), resume.get("total", 0)
                )

            if stream_fields and "streamdetails" in item:
                for key, streams in item["streamdetails"].items():
                    for stream in streams:
                        method = getattr(
                            video_info, f"add{stream_fields.get(key)}", None
                        )
                        if method:
                            method(
                                xbmc.VideoStreamDetail(**stream)
                                if key == "video"
                                else xbmc.AudioStreamDetail(*stream.values())
                            )

            return li_item

        return wrapper

    return decorator


@videoinfotag_setter(
    "",
    {
        "director": "Directors",
        "genre": "Genres",
        "studio": "Studios",
        "writer": "Writers",
    },
)
def set_helper(item):
    """
    Builds a Kodi ListItem for helper service using mapped metadata and artwork.

    :param item: Dictionary containing item metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(
        item,
        item.get("label"),
        "DefaultVideo.png",
        properties={"unwatchedepisodes": item.get("unwatchedepisodes", "0")},
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
    stream_fields={"video": "VideoStreamDetail", "audio": "AudioStreamDetail"},
)
def set_movie(item):
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
def set_tvshow(item):
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
    stream_fields={"video": "VideoStreamDetail", "audio": "AudioStreamDetail"},
)
def set_episode(item):
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
    stream_fields={"video": "VideoStreamDetail", "audio": "AudioStreamDetail"},
)
def set_musicvideo(item):
    """
    Builds a Kodi ListItem for a music video using mapped metadata and artwork.

    :param item: Dictionary containing music video metadata.
    :returns: xbmcgui.ListItem with enriched VideoInfoTag.
    """
    return create_li_item(item, item.get("title"), "DefaultVideo.png")
