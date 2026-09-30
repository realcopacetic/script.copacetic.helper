# author: realcopacetic

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, json_call, to_float, to_int


def trailer_source() -> str:
    """
    Infolabel prefix of the item the trailer was requested for, or "".

    :return: e.g. "Container(3200).ListItem" for a container id, else as stored.
    """
    source = infolabel("Window(home).Property(trailer_source)")
    return f"Container({source}).ListItem" if source.isdigit() else source


class TrailerZoomController:
    """
    Handle trailer zoom based on viewport and content aspect ratio.
    """

    SCREEN_AR = 16 / 9  # frame-fitting basis; viewport WxH is in skin coords
    OVERSCAN = 1.04  # absorb matte variance between trailer encodes and library AR

    def apply_zoom_if_needed(self) -> None:
        """
        Set a new trailer's view mode: zoomed past burned-in bars when an
        inset trailer viewport is active, else normal.
        """
        zoom = 1.0
        if (ar_window := self._get_viewport_ar()) > 0.0:
            content_ar = self._get_content_ar()
            zoom = self._compute_zoom(content_ar=content_ar, window_ar=ar_window)
            log.debug(
                f"PlayerMonitor → Trailer zoom → {content_ar=}, {ar_window=}, {zoom=}"
            )
        self._set_zoom(zoom)

    def _get_viewport_ar(self) -> float:
        """
        Parse trailer viewport WxH from window property and return AR.

        :return: Viewport aspect ratio or 0.0 if missing.
        """
        vp = infolabel("Window(home).Property(trailer_viewport)")
        if not vp:
            return 0.0

        if "x" not in vp:
            return 0.0

        try:
            w, h = map(float, vp.lower().split("x"))
            return round(w / h, 6)

        except Exception as exc:
            log.debug(
                f"PlayerMonitor → Trailer zoom → Viewport parse error for {vp}: {exc}"
            )
            return 0.0

    def _set_zoom(self, zoom: float) -> None:
        """
        Zoom by a factor above 1.0, else select the normal view mode, which
        overrides any zoom Kodi stored for the file.

        :param zoom: Zoom factor; 1.0 or less means none.
        """
        json_call(
            method="Player.SetViewMode",
            params={"viewmode": {"zoom": zoom} if zoom > 1.0 else "normal"},
            parent="TrailerZoom",
        )

    def _get_trailer_dar(self) -> float:
        """
        Get VideoDAR as reported by the player.

        :return: DAR value or 0.0.
        """
        return to_float(infolabel("Player.Process(VideoDAR)"))

    def _get_tvshow_episode_ar(self, tvshow_id: int) -> float:
        """
        Return the display aspect ratio of a TV show's first episode.

        :param tvshow_id: Kodi tvshow database id.
        :return: Aspect ratio value or 0.0.
        """
        result = json_call(
            "VideoLibrary.GetEpisodes",
            properties=["streamdetails"],
            limit=1,
            params={"tvshowid": tvshow_id},
            parent="TrailerZoom_episode_ar",
        )
        episodes = result.get("result", {}).get("episodes", [])
        streams = episodes[0]["streamdetails"]["video"] if episodes else []
        return streams[0]["aspect"] if streams else 0.0

    def _get_content_ar(self) -> float:
        """
        Select the most reliable content aspect ratio: the trailer's own unless
        it reports 16:9, else the library item's, else a TV show's first episode.

        :return: Aspect ratio value or 0.0.
        """
        source = trailer_source()
        trailer_ar = self._get_trailer_dar()
        source_ar = to_float(infolabel(f"{source}.VideoAspect")) if source else 0.0
        episode_ar = 0.0

        # Prefer trailer AR if YouTube not reporting as 16:9
        if trailer_ar and abs(trailer_ar - 1.78) > 0.05:
            content_ar = trailer_ar
        elif source_ar > 0.0:
            content_ar = source_ar
        else:
            dbid = to_int(infolabel(f"{source}.DBID")) if source else 0
            if dbid > 0 and infolabel(f"{source}.DBType").lower() == "tvshow":
                episode_ar = self._get_tvshow_episode_ar(dbid)
            content_ar = episode_ar

        log.debug(
            f"PlayerMonitor → AR select → {trailer_ar=}, {source_ar=}, {episode_ar=}, {content_ar=}"
        )
        return content_ar

    def _compute_zoom(self, content_ar: float, window_ar: float) -> float:
        """
        Compute zoom to fill the viewport in both axes — fill-height kills
        letterbox bars, fill-width kills pillarbox bars — with slight overshoot.

        :param content_ar: Content aspect ratio.
        :param window_ar: Viewport aspect ratio.
        :return: Zoom factor, 1.0 means no zoom.
        """
        if content_ar <= 0.0:
            return 1.0

        fill_height = content_ar / window_ar
        fill_width = self.SCREEN_AR / content_ar
        return round(max(fill_height, fill_width) * self.OVERSCAN, 3)
