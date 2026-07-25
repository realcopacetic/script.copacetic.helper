# author: realcopacetic

from xbmc import PlayList

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import condition, infolabel, json_call

PLAYLIST_VIDEO = 1
WALK_PROPERTIES = ["file"]


class PlayNextQueue:
    def ensure_successor(self, dbid: int, tvshowid: int) -> None:
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
        if self._successor_present():
            return

        next_id = self._next_episode_id(dbid, tvshowid)
        if not next_id:
            return

        self._append(next_id)

    def _successor_present(self) -> bool:
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

    def _next_episode_id(self, dbid: int, tvshowid: int) -> int | None:
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
        episodes = response.get("result", {}).get("episodes", [])
        current_file = infolabel("Player.Filenameandpath")

        found = False
        for episode in episodes:
            if not found:
                found = episode["episodeid"] == dbid
                continue
            if episode["file"] == current_file:
                continue
            return episode["episodeid"]
        return None

    def _append(self, episodeid: int) -> None:
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
