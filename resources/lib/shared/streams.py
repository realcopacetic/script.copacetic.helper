# author: realcopacetic

import re

from resources.lib.shared.utilities import json_call

# Player.GetProperties names per stream type: the list, the one in use, its switch
_STREAMS = {
    "audio": ["audiostreams", "currentaudiostream"],
    "subtitle": ["subtitles", "currentsubtitle", "subtitleenabled"],
    "video": ["videostreams", "currentvideostream"],
}
# Words in a subtitle's name that mark it for the hearing impaired
_IMPAIRED_WORDS = frozenset({"cc", "hi", "sdh"})
# Words that undo "forced" in a subtitle's name (Non-Forced, Not forced)
_NEGATIONS = frozenset({"non", "not"})
# Subtitle types looked for, in order, for each preferred type
_FALLBACKS = {
    "forced": ("forced",),
    "full": ("full", "impaired"),
    "impaired": ("impaired", "full"),
}


def player_streams(type: str) -> tuple[list[dict], dict | None]:
    """
    The playing video's streams of a type, from JSON-RPC, and the one in use:
    None when there is none, and for subtitles while they are off.

    :param type: audio, subtitle or video.
    :return: The streams in index order, and the one in use.
    """
    listed, current, *_ = _STREAMS[type]
    result = json_call(
        "Player.GetProperties",
        properties=_STREAMS[type],
        params={"playerid": 1},  # 1 = video player
        parent="player_streams",
    ).get("result", {})
    in_use = result.get(current) if result.get("subtitleenabled", True) else None
    return result.get(listed, []), in_use or None  # {} when no stream is in use


def subtitle_kind(stream: dict) -> str:
    """
    A subtitle stream's type, from its flags, then words in its name (external
    files carry only forced); "Non-Forced" and "Not forced" are not forced.

    :param stream: A JSON-RPC subtitle stream.
    :return: forced, impaired or full.
    """
    words = set(re.findall(r"[a-z]+", stream["name"].lower()))
    if stream["isforced"] or "forced" in words and not words & _NEGATIONS:
        return "forced"
    if stream["isimpaired"] or words & _IMPAIRED_WORDS:
        return "impaired"
    return "full"


def preferred_subtitle(streams: list[dict], lang: str, kind: str) -> dict | None:
    """
    The first lang stream of kind, else of its fallback: full and impaired
    stand in for each other, forced has none.

    :param streams: The JSON-RPC subtitle streams.
    :param lang: ISO 639-2/B language code, as streams carry it.
    :param kind: forced, full or impaired; empty counts as full.
    :return: The preferred stream, or None without one.
    """
    return next(
        (
            stream
            for wanted in _FALLBACKS[kind or "full"]
            for stream in streams
            if stream["language"] == lang and subtitle_kind(stream) == wanted
        ),
        None,
    )


def subtitle_status(
    streams: list[dict], current: dict | None, lang: str = "", kind: str = ""
) -> str:
    """
    player_subtitle_kind's value: the showing stream's type; while off, "missing"
    when lang is set and has no preferred stream, else "".

    :param streams: The JSON-RPC subtitle streams.
    :param current: The stream showing, None while off.
    :param lang: Preferred ISO 639-2/B language code; empty for none.
    :param kind: Preferred type, as for preferred_subtitle.
    :return: forced, full, impaired, missing or "".
    """
    if current:
        return subtitle_kind(current)
    return "missing" if lang and not preferred_subtitle(streams, lang, kind) else ""
