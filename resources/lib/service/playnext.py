# author: realcopacetic

from xbmc import PlayList

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import condition, infolabel, json_call

PLAYLIST_VIDEO = 1
WALK_PROPERTIES = ["file"]


def ensure_successor(dbid: int, tvshowid: int) -> None:
    """
    Append the next episode of the show to the video playlist if the
    feature is enabled and no successor is already queued. Called once
    per episode from onAVStarted; strict season/episode order.
    :param dbid: Library episodeid of the episode now playing.
    :param tvshowid: Library tvshowid of its show.
    :return: None.
    """
    if not condition("Skin.HasSetting(playnext_enabled)"):
        return
    if _successor_present():
        return

    next_id = _next_episode_id(dbid, tvshowid)
    if not next_id:
        return

    _append(next_id)


def _successor_present() -> bool:
    """
    Report whether the current playlist item already has a successor.
    A negative position means playback did not come from the playlist
    player, so nothing is queued (fail-safe: treat as present).
    :return: Boolean.
    """
    playlist = PlayList(PLAYLIST_VIDEO)
    position = playlist.getposition()
    if position < 0:
        return True
    return position < playlist.size() - 1


def _next_episode_id(dbid: int, tvshowid: int) -> int | None:
    """
    Walk the show's episodes in season/episode order and return the
    episodeid following the one now playing. Entries sharing the
    current file are skipped so multi-part episodes are not requeued.
    :param dbid: Library episodeid of the episode now playing.
    :param tvshowid: Library tvshowid of its show.
    :return: The successor episodeid, or None at the end of the show.
    """
    response = json_call(
        "VideoLibrary.GetEpisodes",
        properties=WALK_PROPERTIES,
        sort={"method": "episode"},
        params={"tvshowid": tvshowid},
        parent="playnext",
    )
    episodes = iter(response.get("result", {}).get("episodes", []))
    current_file = infolabel("Player.Filenameandpath")

    # Consume up to and including the playing episode, then take the next
    # one that isn't another part of the same file.
    any(episode["episodeid"] == dbid for episode in episodes)
    return next((e["episodeid"] for e in episodes if e["file"] != current_file), None)


def _append(episodeid: int) -> None:
    """
    Append the episode to the video playlist via JSON-RPC.
    :param episodeid: Library episodeid to queue.
    :return: None.
    """
    json_call(
        "Playlist.Add",
        params={"playlistid": PLAYLIST_VIDEO, "item": {"episodeid": episodeid}},
        parent="playnext",
    )
    log.debug(f"playnext: queued episodeid {episodeid}")
