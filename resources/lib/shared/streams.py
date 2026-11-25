# author: realcopacetic

import re
from collections.abc import Sequence

import xbmc

from resources.lib.shared.utilities import json_call

# Player.GetProperties names per stream type: the list, the one in use, its switch
_STREAMS = {
    "audio": ["audiostreams", "currentaudiostream"],
    "subtitle": ["subtitles", "currentsubtitle", "subtitleenabled"],
    "video": ["videostreams", "currentvideostream"],
}
# Words in a subtitle's name that mark it for the hearing impaired
_IMPAIRED_WORDS = frozenset({"cc", "hi", "sdh"})
# Words in a subtitle's name that mark a commentary, never picked as preferred
_COMMENTARY_WORDS = frozenset({"commentary", "commentaries"})
# "forced" negated in a subtitle's name: Non-Forced, Not forced (not "non-English")
_NOT_FORCED = re.compile(r"\bno[nt][\s-]*forced\b")
# Subtitle types looked for, in order, for each preferred type
_FALLBACKS = {
    "forced": ("forced",),
    "full": ("full", "impaired"),
    "impaired": ("impaired", "full"),
}


def player_streams(type: str) -> tuple[list[dict], dict | None, dict | None]:
    """
    The playing video's streams of a type, from JSON-RPC, the one in use (None
    for subtitles while they are off) and the one selected, Kodi's even while off.

    :param type: audio, subtitle or video.
    :return: The streams in index order, the one in use, the one selected.
    """
    listed, current, *_ = _STREAMS[type]
    result = json_call(
        "Player.GetProperties",
        properties=_STREAMS[type],
        params={"playerid": 1},  # 1 = video player
        parent="player_streams",
    ).get("result", {})
    selected = result.get(current) or None  # {} when no stream is selected
    shown = result.get("subtitleenabled", True)
    return result.get(listed, []), selected if shown else None, selected


def subtitle_kind(stream: dict) -> str:
    """
    A subtitle stream's type, from its flags, then words in its name (external
    files carry only forced); "Non-Forced" and "Not forced" are not forced.

    :param stream: A JSON-RPC subtitle stream.
    :return: forced, impaired or full.
    """
    name = stream["name"].lower()
    words = set(re.findall(r"[a-z]+", name))
    if stream["isforced"] or "forced" in words and not _NOT_FORCED.search(name):
        return "forced"
    if stream["isimpaired"] or words & _IMPAIRED_WORDS:
        return "impaired"
    return "full"


def iso639_2(lang: str) -> str:
    """
    A language code or English name (on Kodi 22 also a BCP 47 tag, "en-AU") as
    its ISO 639-2/B code, via 639-1 as Kodi does, so 639-2/T "deu" gives "ger";
    unknown ones stay as given. Streams carry the code on Omega, a tag on Kodi 22.

    :param lang: A language (e.g. "en", "en-AU", "deu", "English").
    :return: Its ISO 639-2/B code (e.g. "eng", "ger").
    """
    two = xbmc.convertLanguage(lang, xbmc.ISO_639_1) or lang
    return xbmc.convertLanguage(two, xbmc.ISO_639_2) or lang


def preferred_subtitle(streams: list[dict], lang: str, kind: str) -> dict | None:
    """
    The first lang stream of kind, else of its fallback: full and impaired
    stand in for each other, forced has none. Commentaries are passed over.

    :param streams: The JSON-RPC subtitle streams.
    :param lang: ISO 639-2/B language code, as iso639_2 gives it.
    :param kind: forced, full or impaired; empty counts as full.
    :return: The preferred stream, or None without one.
    """
    in_lang = [
        stream
        for stream in streams
        if iso639_2(stream["language"]) == lang
        and _COMMENTARY_WORDS.isdisjoint(re.findall(r"[a-z]+", stream["name"].lower()))
    ]
    return next(
        (
            stream
            for wanted in _FALLBACKS[kind or "full"]
            for stream in in_lang
            if subtitle_kind(stream) == wanted
        ),
        None,
    )


def subtitle_status(
    streams: list[dict],
    current: dict | None,
    langs: Sequence[str] = (),
    kind: str = "",
) -> str:
    """
    player_subtitle_kind's value: the showing stream's type; while off, "missing"
    when languages are set and none has a preferred stream, else "".

    :param streams: The JSON-RPC subtitle streams.
    :param current: The stream showing, None while off.
    :param langs: Preferred ISO 639-2/B language codes; empty for none.
    :param kind: Preferred type, as for preferred_subtitle.
    :return: forced, full, impaired, missing or "".
    """
    if current:
        return subtitle_kind(current)
    found = any(preferred_subtitle(streams, lang, kind) for lang in langs)
    return "missing" if langs and not found else ""
