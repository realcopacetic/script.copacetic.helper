# author: realcopacetic

from xbmc import PlayList

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import condition, infolabel, json_call

PLAYLIST_VIDEO = 1
WALK_PROPERTIES = ["file"]


def ensure_successor(dbid: int, tvshowid: int) -> str | None:
    """
    Append the next episode of the show to the video playlist if the feature is
    enabled and no successor is queued. Once per episode from onAVStarted.
    :param dbid: Library episodeid of the episode now playing.
    :param tvshowid: Library tvshowid of its show.
    :return: The queued episode's file, or None when nothing was queued.
    """
    if not condition("Skin.HasSetting(playnext_enabled)") or _successor_present():
        return None
    if successor := _next_episode(dbid, tvshowid):
        _append(successor["episodeid"])
        return successor["file"]
    return None


def withdraw(file: str) -> None:
    """
    Remove the successor ensure_successor queued while it is still the next item:
    Play next was switched off during its episode.
    :param file: The queued episode's file.
    """
    playlist = PlayList(PLAYLIST_VIDEO)
    position = playlist.getposition() + 1
    if 0 < position < playlist.size() and playlist[position].getPath() == file:
        json_call(
            "Playlist.Remove",
            params={"playlistid": PLAYLIST_VIDEO, "position": position},
            parent="playnext",
        )
        log.debug(f"playnext: withdrew {file}")


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


def _next_episode(dbid: int, tvshowid: int) -> dict | None:
    """
    Walk the show's episodes in season/episode order to the one after the one
    playing, skipping other parts of the same file (multi-part episodes).
    :param dbid: Library episodeid of the episode now playing.
    :param tvshowid: Library tvshowid of its show.
    :return: The successor's episodeid and file, or None at the end of the show.
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
    return next((e for e in episodes if e["file"] != current_file), None)


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
