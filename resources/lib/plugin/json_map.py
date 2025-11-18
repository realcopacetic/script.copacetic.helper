# author: realcopacetic, sualfred

from resources.lib.plugin.setter import TAG_TYPES

JSON_PROPERTIES: dict[str, list[str]] = {
    "movie": [
        "title",
        "year",
        "director",
        "trailer",
        "tagline",
        "plot",
        "plotoutline",
        "lastplayed",
        "playcount",
        "studio",
        "mpaa",
        "runtime",
        "streamdetails",
        "file",
        "resume",
        "art",
        "movieid",
    ],
    "episode": [
        "title",
        "plot",
        "firstaired",
        "playcount",
        "runtime",
        "season",
        "episode",
        "showtitle",
        "streamdetails",
        "lastplayed",
        "file",
        "resume",
        "tvshowid",
        "art",
        "episodeid",
    ],
    "tvshow": [
        "title",
        "year",
        "plot",
        "studio",
        "mpaa",
        "playcount",
        "episode",
        "lastplayed",
        "file",
        "season",
        "watchedepisodes",
        "art",
        "tvshowid",
    ],
    "musicvideo": [
        "title",
        "playcount",
        "runtime",
        "studio",
        "year",
        "artist",
        "streamdetails",
        "lastplayed",
        "file",
        "resume",
        "art",
        "musicvideoid",
    ],
    "season": [
        "season",
        "showtitle",
        "playcount",
        "episode",
        "fanart",
        "thumbnail",
        "tvshowid",
        "watchedepisodes",
        "art",
        "userrating",
        "title",
    ],
    "artist": [
        "instrument",
        "style",
        "mood",
        "born",
        "formed",
        "description",
        "genre",
        "died",
        "disbanded",
        "yearsactive",
        "musicbrainzartistid",
        "fanart",
        "thumbnail",
        "compilationartist",
        "dateadded",
        "roles",
        "songgenres",
        "isalbumartist",
        "artistid",
    ],
    "playlist": [
        "title",
        "artist",
        "albumartist",
        "genre",
        "year",
        "rating",
        "album",
        "track",
        "duration",
        "comment",
        "lyrics",
        "musicbrainztrackid",
        "musicbrainzartistid",
        "musicbrainzalbumid",
        "musicbrainzalbumartistid",
        "playcount",
        "fanart",
        "director",
        "trailer",
        "tagline",
        "plot",
        "plotoutline",
        "originaltitle",
        "lastplayed",
        "writer",
        "studio",
        "mpaa",
        "cast",
        "country",
        "imdbnumber",
        "premiered",
        "productioncode",
        "runtime",
        "set",
        "showlink",
        "streamdetails",
        "top250",
        "votes",
        "firstaired",
        "season",
        "episode",
        "showtitle",
        "thumbnail",
        "file",
        "resume",
        "artistid",
        "albumid",
        "tvshowid",
        "setid",
        "watchedepisodes",
        "disc",
        "tag",
        "art",
        "genreid",
        "displayartist",
        "albumartistid",
        "description",
        "theme",
        "mood",
        "style",
        "albumlabel",
        "sorttitle",
        "episodeguide",
        "uniqueid",
        "dateadded",
        "channel",
        "channeltype",
        "hidden",
        "locked",
        "channelnumber",
        "starttime",
        "endtime",
        "specialsortseason",
        "specialsortepisode",
        "compilation",
        "releasetype",
        "albumreleasetype",
        "contributors",
        "displaycomposer",
        "displayconductor",
        "displayorchestra",
        "displaylyricist",
        "userrating",
    ],
}

JSON_FIELD_MAP: dict[str, str] = {
    "artist": "Artists",
    "director": "Directors",
    "dbid": "DbId",
    "episode": "Episode",
    "episodeid": "DbId",
    "firstaired": "Premiered",
    "genre": "Genres",
    "lastplayed": "LastPlayed",
    "movieid": "DbId",
    "mpaa": "Mpaa",
    "musicvideoid": "DbId",
    "playcount": "Playcount",
    "plot": "Plot",
    "plotoutline": "PlotOutline",
    "runtime": "Duration",
    "season": "Season",
    "showtitle": "TvShowTitle",
    "studio": "Studios",
    "tagline": "TagLine",
    "title": "Title",
    "top250": "Top250",
    "track": "TrackNumber",
    "trailer": "Trailer",
    "tvshowid": "DbId",
    "writer": "Writers",
    "year": "Year",
}


def json_to_canonical(
    raw: dict,
    content_type: str,
    allowed: set[str] | None = None,
) -> dict:
    """
    Convert a raw Kodi JSON-RPC VideoLibrary item into a canonical metadata dict.

    :param raw: Raw dictionary returned by VideoLibrary.*.
    :param content_type: Logical type (``"movie"``, ``"tvshow"``, ``"episode"``, ...).
    :param allowed: Optional whitelist of canonical tag names.
    :return: Canonical metadata dictionary ready for ``set_items()``.
    """
    item: dict[str, str | int | list] = {
        "file": raw.get("file", ""),
        "art": raw.get("art", {}) or {},
        "properties": {},
    }

    item["label"] = raw.get("label", "")
    item["label2"] = raw.get("label2", "")

    if isinstance(raw.get("resume"), dict):
        item["resume"] = raw["resume"]

    if isinstance(raw.get("streamdetails"), dict):
        item["streamdetails"] = raw["streamdetails"]

    for json_key in JSON_PROPERTIES.get(content_type, []):
        if json_key not in raw:
            continue

        canonical = JSON_FIELD_MAP.get(json_key)
        if canonical is None:
            continue

        if allowed and canonical not in allowed:
            continue

        if canonical in TAG_TYPES:
            item[canonical] = raw[json_key]

    return item
