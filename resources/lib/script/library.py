# author: realcopacetic

import errno
import socket
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import cache
from http.client import HTTPException
from itertools import islice
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

import xbmcvfs
from xbmc import getCacheThumbName

from resources.lib.apis.http import USER_AGENT
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    DETAILS,
    json_call,
    url_decode_path,
)

# kind: (list method, result key, id key, set method)
LIBRARY = {
    "artists": (
        "AudioLibrary.GetArtists",
        "artists",
        "artistid",
        "AudioLibrary.SetArtistDetails",
    ),
    "albums": (
        "AudioLibrary.GetAlbums",
        "albums",
        "albumid",
        "AudioLibrary.SetAlbumDetails",
    ),
    "songs": ("AudioLibrary.GetSongs", "songs", "songid", None),
    "movies": (
        "VideoLibrary.GetMovies",
        "movies",
        "movieid",
        "VideoLibrary.SetMovieDetails",
    ),
    "sets": (
        "VideoLibrary.GetMovieSets",
        "sets",
        "setid",
        "VideoLibrary.SetMovieSetDetails",
    ),
    "tvshows": (
        "VideoLibrary.GetTVShows",
        "tvshows",
        "tvshowid",
        "VideoLibrary.SetTVShowDetails",
    ),
    "seasons": (
        "VideoLibrary.GetSeasons",
        "seasons",
        "seasonid",
        "VideoLibrary.SetSeasonDetails",
    ),
    "episodes": ("VideoLibrary.GetEpisodes", "episodes", "episodeid", None),
    "musicvideos": ("VideoLibrary.GetMusicVideos", "musicvideos", "musicvideoid", None),
}
# only network shares: a local path may exist on one device and not another
SHARE_SCHEMES = ("smb://", "nfs://")
LOCAL_HOSTS = (".local", ".lan", ".home", ".internal", ".arpa")
DEAD_STATUS = {404, 410}
NO_HOST = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
CHECK_WORKERS = 8
URL_SAFE = ":/?&=%#+@;,!$'()*[]~"
# list params past the GUI's own filters: remove_broken_art checks song artists (the
# refresh-all can list them) and singles; clean_image_cache keeps every role too
CHECKED = {"artists": {"albumartistsonly": False}, "albums": {"includesingles": True}}
EVERYTHING = {**CHECKED, "artists": {"albumartistsonly": False, "allroles": True}}
SILENT_AFTER = 3
PROBE_EVERY = 50  # a silenced host still gets one link in 50, so it can come back
UNREACHABLE = {errno.EHOSTUNREACH, errno.ENETUNREACH}
# failures and skips per host this run; from SILENT_AFTER its links are skipped,
# bar a probe every PROBE_EVERY
_silence: Counter[str] = Counter()


def library_art(
    kind: str, params: dict | None = None
) -> list[tuple[int, str, dict[str, str]]]:
    """
    Every item of a library kind that has art of its own; types inherited from a
    parent (tvshow.poster, album.thumb) are left out.

    :param kind: A LIBRARY key.
    :param params: Extra list params, e.g. EVERYTHING's.
    :return: (id, label, {art type: URL as Kodi returns it}) per item.
    """
    method, key, id_key, _ = LIBRARY[kind]
    # songs: art is quicker with albumid (Omega AudioLibrary.cpp GetSongs)
    properties = ["art", "albumid"] if kind == "songs" else ["art"]
    items = json_call(
        method, properties=properties, params=params, parent="library_art"
    )["result"]
    return [
        (item[id_key], item["label"], own)
        for item in items.get(key, [])
        if (own := {art: url for art, url in item["art"].items() if "." not in art})
    ]


def remove_art(kind: str, item_id: int, art_types: Iterable[str]) -> None:
    """
    Remove art types from one library item: Set*Details removes a type set to null.

    :param kind: A LIBRARY key with a set method.
    :param item_id: The item's library id.
    :param art_types: Art types to remove.
    """
    _, _, id_key, method = LIBRARY[kind]
    json_call(
        method,
        params={id_key: item_id, "art": dict.fromkeys(art_types)},
        parent="remove_art",
    )


def _details(type: str, dbid: int, *properties: str) -> dict:
    """
    One library item's details.

    :param type: A DETAILS key.
    :param dbid: The item's library id.
    :param properties: Properties to fetch.
    :return: The details object.
    """
    return json_call(
        DETAILS[type],
        properties=list(properties),
        params={f"{type}id": dbid},
        parent="refresh_cached",
    )["result"][f"{type}details"]


def api_patterns(type: str, dbid: int) -> list[str]:
    """
    LIKE patterns for an item's api_cache rows: a movie's TMDb rows, a show's and its
    seasons' for a show, season or episode, and ListenBrainz's for a music item.

    :param type: A DETAILS key.
    :param dbid: The item's library id.
    :return: Patterns, none when the item has no id the APIs know it by.
    """
    if type in ("artist", "album", "song"):
        from resources.lib.apis.listenbrainz import musicbrainz_id

        _, mbid = musicbrainz_id(type, dbid, "refresh_cached")
        return [f"listenbrainz:%:{mbid}"] if mbid else []
    if type in ("season", "episode"):
        type, dbid = "tvshow", _details(type, dbid, "tvshowid")["tvshowid"]
    if type not in ("movie", "tvshow"):
        return []
    if not (tmdb := _details(type, dbid, "uniqueid")["uniqueid"].get("tmdb")):
        return []
    kinds = ("movie",) if type == "movie" else ("tvshow", "season_%")
    return [f"tmdb:{kind}:{tmdb}:%" for kind in kinds]


def remove_textures(urls: Iterable[str] = (), prefixes: Iterable[str] = ()) -> int:
    """
    Remove this device's cached copies of these images and of any under these path
    prefixes, so their next load reads them again.

    :param urls: Image URLs, wrapped or plain.
    :param prefixes: Plain path prefixes.
    :return: How many were removed.
    """
    exact, prefixes = {url_decode_path(url) for url in urls}, tuple(prefixes)
    rules = [
        *({"field": "url", "operator": "is", "value": url} for url in exact),
        *({"field": "url", "operator": "startswith", "value": p} for p in prefixes),
    ]
    if not rules:
        return 0
    # Kodi makes both operators an unescaped LIKE (DatabaseQuery.cpp): match again
    textures = [
        texture
        for texture in json_call(
            "Textures.GetTextures",
            properties=["url"],
            query_filter={"or": rules},
            parent="remove_textures",
        )["result"].get("textures", [])
        if (url := url_decode_path(texture["url"])) in exact or url.startswith(prefixes)
    ]
    for texture in textures:
        json_call(
            "Textures.RemoveTexture",
            params={"textureid": texture["textureid"]},
            parent="remove_textures",
        )
    return len(textures)


def refresh_cached(type: str, dbid: int) -> int:
    """
    Mark one item's API answers stale and forget its art's processed rows and this
    device's copies of its art, so each is made again when next shown.

    :param type: A DETAILS key.
    :param dbid: The item's library id.
    :return: How many answers, rows and copies it changed.
    """
    from resources.lib.shared.sqlite import ApiCacheHandler, ArtworkCacheHandler

    count = ApiCacheHandler().expire(*api_patterns(type, dbid))
    art = [
        url
        for name, url in _details(type, dbid, "art")["art"].items()
        if "." not in name
    ]
    # processed rows hold the URL as the skin passed it, which the plugin unquotes
    # once: wrapped, plain or (embedded art) once-unquoted
    forms = set()
    for url in art:
        decoded = url_decode_path(url)
        forms |= {url, decoded, unquote(decoded)}
    count += ArtworkCacheHandler().delete_sources(forms)
    # outputs of a source Kodi hadn't cached are named by its URL and rewritten in
    # place (art/cache.py with_process_variant): drop Kodi's copies of those
    stems = {
        getCacheThumbName(url_decode_path(url)).removesuffix(".tbn") for url in art
    }
    prefixes = [str(Path(folder) / stem) for folder in (BLURS, CROPS) for stem in stems]
    # a source that can't be read now keeps its copy: it may be the only one left
    readable = [url for url in art if check(url) is None]
    return count + remove_textures(readable, prefixes)


def online() -> bool:
    """Whether names resolve, so a host that doesn't is gone rather than offline."""
    return _resolves("image.tmdb.org")


def _path(url: str) -> str:
    """
    The file or web address an art URL opens, without Kodi's |Header=value options.

    :param url: Art URL as Kodi returns it (image:// wrapped).
    :return: Plain path or URL.
    """
    return url_decode_path(url).partition("|")[0]


def _gate(path: str) -> str:
    """
    The folder that must answer before a miss counts: an smb file's share root, an
    nfs file's grandparent (an NFSv3 export may sit deeper than the first folder).

    :param path: Share path.
    :return: Folder path ending in /.
    """
    if path.startswith("nfs://"):
        return path.rsplit("/", 2)[0] + "/"
    scheme, _, rest = path.partition("://")
    return f"{scheme}://" + "/".join(rest.split("/")[:2]) + "/"


_LISTING = Lock()


def _listing(folder: str) -> tuple[set[str], set[str]] | None:
    """
    A folder's sub-folder and file names, lower case, read once per run (one thread
    at a time, so eight never wait on the same asleep share); None if unreadable.

    :param folder: Folder path ending in /.
    :return: (folders, files), or None.
    """
    with _LISTING:
        return _read_listing(folder)


@cache
def _read_listing(folder: str) -> tuple[set[str], set[str]] | None:
    """
    A folder's names, lower case; None when it can't be read or is empty (Kodi's
    listdir can't tell those apart).

    :param folder: Folder path ending in /.
    :return: (folders, files), or None.
    """
    folders, files = xbmcvfs.listdir(folder)
    if not (folders or files):
        return None
    return {name.lower() for name in folders}, {name.lower() for name in files}


def _listed(name: str, names: set[str]) -> bool:
    """
    Whether a name is in a lower-cased listing, raw or URL-decoded.

    :param name: File or folder name from a library path.
    :param names: Lower-cased names from _listing.
    :return: True when listed.
    """
    return name.lower() in names or unquote(name).lower() in names


def _share_status(path: str) -> str | None:
    """
    "gone" when a share file is missing for certain: the share answers, the file
    doesn't, and its folder's listing lacks it (or the parent's lacks the folder).

    :param path: smb:// or nfs:// file path.
    :return: "gone", "skipped" (the share didn't answer) or None.
    """
    if _listing(_gate(path)) is None:
        return "skipped"  # the share is asleep or refuses this device
    if xbmcvfs.exists(path):
        return None
    if "/." in path:
        return None  # hidden names are left out of listings
    folder, _, name = path.rpartition("/")
    if (listing := _listing(f"{folder}/")) is not None:
        return None if _listed(name, listing[1]) else "gone"
    parent, _, folder_name = folder.rpartition("/")
    if (listing := _listing(f"{parent}/")) is not None:
        return None if _listed(folder_name, listing[0]) else "gone"
    return None


def _resolves(host: str) -> bool:
    """
    Whether a host name resolves.

    :param host: Host name.
    :return: True when it resolves.
    """
    try:
        socket.getaddrinfo(host, 443)
    except OSError:
        return False
    return True


def _web_status(url: str) -> str | None:
    """
    How a web image answers: "gone" for 404 or 410 (HEAD, then a one-byte GET, as
    some servers refuse HEAD), "host" when its name doesn't resolve, else None.

    :param url: Plain http(s) URL.
    :return: "gone", "host", "skipped" (host silent, or a lookup failed for now), None.
    """
    try:
        host = urlsplit(url).hostname
    except ValueError:  # a malformed host, e.g. an unclosed [
        return None
    if (failures := _silence[host]) >= SILENT_AFTER:
        _silence[host] += 1  # claimed first, so workers rarely probe at once
        if failures % PROBE_EVERY:
            return "skipped"
    url = quote(url, safe=URL_SAFE)  # a space or non-ASCII character is still checked
    for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        headers = {"User-Agent": USER_AGENT, **extra}
        try:
            with urlopen(Request(url, method=method, headers=headers), timeout=10):
                _silence[host] = 0
                return None
        except HTTPError as exc:  # before URLError: it is one
            if exc.code not in DEAD_STATUS:
                _silence[host] = 0
                return None
        except URLError as exc:  # connecting: no name, refused, timed out
            if isinstance(exc.reason, socket.gaierror):
                if exc.reason.errno in NO_HOST:
                    return "host"
                _silence[host] += 1  # a lookup that timed out or failed for now
                return "skipped"
            silent = isinstance(exc.reason, (TimeoutError, ConnectionRefusedError))
            if silent or getattr(exc.reason, "errno", None) in UNREACHABLE:
                _silence[host] += 1
                return "skipped"
            return None
        except TimeoutError:  # connected, then no reply: a hung server
            _silence[host] += 1
            return "skipped"
        except (OSError, ValueError, HTTPException):  # mid-reply reset; bad URL
            return None
    _silence[host] = 0  # both answered 404 or 410: the server is up
    return "gone"


def check(url: str) -> str | None:
    """
    Whether an art URL is gone: "gone" for a dead web image or a missing share
    file, "host" for a host name that didn't resolve, "skipped" if unanswered.

    :param url: Art URL as Kodi returns it (image:// wrapped).
    :return: "gone", "host", "skipped" or None (fine, or uncertain).
    """
    path = _path(url)
    if path.startswith(("http://", "https://")):
        return _web_status(path)
    if path.startswith(SHARE_SCHEMES):
        return _share_status(path)
    return None  # local paths, embedded (music@, video@), transforms, add-on schemes


def broken_urls(
    urls: set[str], progress: Callable[[int], bool]
) -> tuple[set[str], dict[str, str], int] | None:
    """
    Check URLs in parallel, a few in flight at a time. A web host that didn't
    resolve is looked up again afterwards; only public names still failing count.

    :param urls: Art URLs to check.
    :param progress: Called with the count done; returns True to cancel.
    :return: (gone URLs, {URL: dead host}, URLs skipped), or None if cancelled/offline.
    """
    _read_listing.cache_clear()
    _silence.clear()
    found = {"gone": set(), "host": set(), "skipped": set()}
    checked, todo = 0, iter(urls)
    pool = ThreadPoolExecutor(max_workers=CHECK_WORKERS)
    pending = {pool.submit(check, url): url for url in islice(todo, 2 * CHECK_WORKERS)}
    try:
        while pending:
            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                url = pending.pop(future)
                found.get(future.result(), set()).add(url)
            checked += len(done)
            pending |= {pool.submit(check, url): url for url in islice(todo, len(done))}
            if progress(checked):
                return None
    finally:
        # don't wait on checks still running: a cancel closes the dialog at once
        pool.shutdown(wait=False, cancel_futures=True)
    if not online():
        return None
    host = {url: urlsplit(_path(url)).hostname or "" for url in found["host"]}
    public = {
        name
        for name in set(host.values())
        if "." in name and not name.endswith(LOCAL_HOSTS)
    }
    dead = {name for name in public if not _resolves(name)}
    dead_hosts = {url: host[url] for url in found["host"] if host[url] in dead}
    return found["gone"], dead_hosts, len(found["skipped"])
