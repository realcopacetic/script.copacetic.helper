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


def subtitle_kind(stream: dict | None) -> str:
    """
    A subtitle stream's type: forced, impaired or full, from its flags, then
    words in its name (external files carry only forced); "" for None.
    """
    if not stream:
        return ""
    words = set(re.findall(r"[a-z]+", stream["name"].lower()))
    if stream["isforced"] or "forced" in words:
        return "forced"
    if stream["isimpaired"] or words & _IMPAIRED_WORDS:
        return "impaired"
    return "full"
