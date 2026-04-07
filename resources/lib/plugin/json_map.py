# author: realcopacetic, sualfred

from resources.lib.plugin.setter import TAG_TYPES
from resources.lib.shared import logger as log

_JSON_TO_CANONICAL: dict[str, str] = {
    spec["json"]: canonical
    for canonical, spec in TAG_TYPES.items()
    if spec.get("json")
}

JSON_PROPERTIES: dict[str, list[str]] = {
    "album": [
        "title",
        "description",
        "artist",
        "genre",
        "theme",
        "mood",
        "style",
        "type",
        "albumlabel",
        "rating",
        "votes",
        "userrating",
        "year",
        "musicbrainzalbumid",
        "musicbrainzalbumartistid",
        "playcount",
        "displayartist",
        "compilation",
        "releasetype",
        "dateadded",
        "sortartist",
        "musicbrainzreleasegroupid",
        "art",
        "lastplayed",
        "isboxset",
        "totaldiscs",
        "releasedate",
        "originaldate",
        "albumstatus",
        "datemodified",
        "datenew",
        "albumduration",
    ],
    "artist": [
        "instrument",
        "style",
        "mood",
        "born",
        "formed",
        "description",
        "died",
        "disbanded",
        "yearsactive",
        "musicbrainzartistid",
        "compilationartist",
        "dateadded",
        "isalbumartist",
        "sortname",
        "type",
        "gender",
        "disambiguation",
        "art",
        "datemodified",
        "datenew",
    ],
    "episode": [
        "title",
        "plot",
        "votes",
        "rating",
        "writer",
        "firstaired",
        "playcount",
        "runtime",
        "director",
        "productioncode",
        "season",
        "episode",
        "originaltitle",
        "showtitle",
        "streamdetails",
        "lastplayed",
        "file",
        "resume",
        "tvshowid",
        "dateadded",
        "art",
        "specialsortseason",
        "specialsortepisode",
        "userrating",
        "seasonid",
    ],
    "movie": [
        "title",
        "genre",
        "year",
        "rating",
        "director",
        "trailer",
        "tagline",
        "plot",
        "plotoutline",
        "originaltitle",
        "lastplayed",
        "playcount",
        "writer",
        "studio",
        "mpaa",
        "country",
        "runtime",
        "set",
        "streamdetails",
        "top250",
        "votes",
        "file",
        "sorttitle",
        "resume",
        "setid",
        "dateadded",
        "art",
        "userrating",
        "premiered",
    ],
    "movieset": [
        "title",
        "playcount",
        "art",
        "plot",
    ],
    "musicvideo": [
        "title",
        "playcount",
        "runtime",
        "director",
        "studio",
        "year",
        "plot",
        "album",
        "artist",
        "genre",
        "track",
        "streamdetails",
        "lastplayed",
        "file",
        "resume",
        "dateadded",
        "art",
        "rating",
        "userrating",
        "premiered",
    ],
    "season": [
        "season",
        "showtitle",
        "playcount",
        "episode",
        "tvshowid",
        "watchedepisodes",
        "art",
        "userrating",
        "title",
    ],
    "song": [
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
        "file",
        "albumid",
        "lastplayed",
        "disc",
        "displayartist",
        "albumreleasetype",
        "dateadded",
        "votes",
        "userrating",
        "mood",
        "contributors",
        "displaycomposer",
        "displayconductor",
        "displayorchestra",
        "displaylyricist",
        "sortartist",
        "art",
        "disctitle",
        "releasedate",
        "originaldate",
        "bpm",
        "samplerate",
        "bitrate",
        "channels",
        "datemodified",
        "datenew",
    ],
    "tvshow": [
        "title",
        "genre",
        "year",
        "rating",
        "plot",
        "studio",
        "mpaa",
        "playcount",
        "episode",
        "premiered",
        "votes",
        "lastplayed",
        "file",
        "originaltitle",
        "sorttitle",
        "season",
        "watchedepisodes",
        "dateadded",
        "art",
        "userrating",
        "runtime",
    ],
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
    id_field = f"{content_type}id"
    if id_field in raw and (allowed is None or "DbId" in allowed):
        item["DbId"] = raw[id_field]

    if isinstance(raw.get("resume"), dict):
        item["resume"] = raw["resume"]

    if isinstance(raw.get("streamdetails"), dict):
        item["streamdetails"] = raw["streamdetails"]

    for json_key in JSON_PROPERTIES.get(content_type, []):
        if json_key not in raw:
            continue

        if json_key == "tvshowid":
            item["properties"]["tvshowid"] = str(raw[json_key])
            continue

        canonical = _JSON_TO_CANONICAL.get(json_key)
        if canonical is None:
            log.debug(
                f"json_to_canonical: requested field {json_key!r} has no "
                f"canonical mapping; field will be silently dropped."
            )
            continue

        if allowed and canonical not in allowed:
            continue

        item[canonical] = raw[json_key]

    return item
