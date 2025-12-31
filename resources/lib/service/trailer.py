# author: realcopacetic

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, json_call, to_float


class TrailerZoomController:
    """
    Handle trailer zoom based on viewport and content aspect ratio.
    """

    def apply_zoom_if_needed(self) -> None:
        """
        Apply zoom when a trailer viewport is active.
        """
        ar_window = self._get_viewport_ar()
        if ar_window <= 0.0:
            log.debug("PlayerMonitor: Trailer zoom skipped → no active viewport")
            return

        self._reset_zoom()
        content_ar = self._get_content_ar()
        zoom = self._compute_zoom(content_ar=content_ar, window_ar=ar_window)

        if zoom > 1.0:
            self._apply_zoom(zoom)

        log.debug(
            f"PlayerMonitor → Trailer zoom → {content_ar=}, {ar_window=}, {zoom=}"
        )

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

    def _reset_zoom(self) -> None:
        """
        Reset Kodi view mode zoom to neutral.
        """
        json_call(
            method="Player.SetViewMode",
            params={"viewmode": {"zoom": 1.0}},
            parent="TrailerZoom_reset",
        )

    def _apply_zoom(self, zoom: float) -> None:
        """
        Apply a zoom factor via JSON-RPC.

        :param zoom: Zoom factor to apply.
        """
        json_call(
            method="Player.SetViewMode",
            params={"viewmode": {"zoom": zoom}},
            parent="TrailerZoom_apply",
        )

    def _get_trailer_dar(self) -> float:
        """
        Get VideoDAR as reported by the player.

        :return: DAR value or 0.0.
        """
        return to_float(infolabel("Player.Process(VideoDAR)"))

    def _get_trailer_source(self) -> str:
        """
        Resolve the active content source prefix for AR lookup.

        :return: e.g. "ListItem" or "Container(3100)".
        """
        raw = (infolabel("Window(home).Property(trailer_source)") or "").strip()
        return f"Container({raw}).ListItem" if raw.isdigit() else "ListItem"

    def _get_source_ar(self) -> float:
        """
        Return AR from the listitem/container feeding the trailer.

        :return: Aspect ratio or 0.0.
        """
        source = self._get_trailer_source()
        return to_float(infolabel(f"{source}.VideoAspect"))

    def _get_tvshow_episode_ar(self, tvshow_id: int) -> float:
        """
        Return aspect ratio of the first episode for a tvshow.

        :param tvshow_id: Kodi tvshow database id.
        :return: Aspect ratio value or 0.0.
        """
        try:
            result = json_call(
                method="VideoLibrary.GetEpisodes",
                params={
                    "tvshowid": tvshow_id,
                    "properties": ["streamdetails"],
                    "limits": {"start": 0, "end": 1},
                },
                parent="TrailerZoom_episode_ar",
            )
        except Exception as exc:
            log.debug(
                f"PlayerMonitor → Trailer zoom → Episode AR JSON error: {exc}"
            )
            return 0.0

        episodes = result.get("result", {}).get("episodes", [])
        if not episodes:
            return 0.0

        video_streams = episodes[0].get("streamdetails", {}).get("video", [])
        if not video_streams:
            return 0.0

        width = video_streams[0].get("width")
        height = video_streams[0].get("height")
        if not width or not height:
            return 0.0

        try:
            ar = round(float(width) / float(height), 3)
        except (TypeError, ValueError, ZeroDivisionError):
            ar = 0.0

        log.debug(
            f"PlayerMonitor → Trailer zoom → Episode AR → {tvshow_id=}, "
            f"{width=}, {height=}, {ar=}"
        )
        return ar

    def _get_content_ar(self) -> float:
        """
        Select the most reliable content aspect ratio.

        :return: Aspect ratio value or 0.0.
        """
        source = self._get_trailer_source()
        trailer_ar = self._get_trailer_dar()
        source_ar = self._get_source_ar()

        # TV show fallback
        episode_ar = 0.0
        dbtype = infolabel(f"{source}.DBType").lower()
        dbid = to_float(infolabel(f"{source}.DBID"))
        if dbtype == "tvshow" and dbid > 0 and source_ar <= 0.0:
            episode_ar = self._get_tvshow_episode_ar(int(dbid))

        # Prefer trailer AR if clearly not fake-16:9
        if trailer_ar and abs(trailer_ar - 1.78) > 0.05:
            content_ar = trailer_ar
        elif source_ar > 0.0:
            content_ar = source_ar
        else:
            content_ar = episode_ar

        log.debug(
            f"PlayerMonitor → AR select → {trailer_ar=}, {source_ar=}, {episode_ar=}, {content_ar=}"
        )
        return content_ar

    def _compute_zoom(self, content_ar: float, window_ar: float) -> float:
        """
        Compute zoom factor to fill the viewport.

        :param content_ar: Content aspect ratio.
        :param window_ar: Viewport aspect ratio.
        :return: Zoom factor, 1.0 means no zoom.
        """
        if content_ar <= 0.0:
            return 1.0

        return round(content_ar / window_ar, 3)
