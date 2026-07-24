# author: realcopacetic

import random
import time
from urllib.parse import parse_qsl

from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    to_int,
    url_decode_path,
    window_property,
)

PROPS = (
    "slideshow_fanart",
    "slideshow_blur",
    "slideshow_clearlogo",
    "slideshow_title",
    "slideshow_darken",
)


class Slideshow:
    """
    Global background slideshow. Publishes one canonical prop set per slide
    (sharp fanart, blurred fanart, cropped clearlogo, title) on a fixed
    interval; all transition presentation is owned by the skin.
    """

    BATCH_SIZE = 20
    DEFAULT_INTERVAL = 5

    LIBRARY_MAP = {"movies": "movies", "tvshows": "tvshows", "music": "artists"}
    TYPE_MAP = {
        "global": ("movies", "tvshows", "music"),
        "videos": ("movies", "tvshows"),
        "artists": ("music",),
    }

    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialise processing pipeline and scheduling state.

        :param sqlite_handler: Optional ArtworkCacheHandler instance.
        """
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor
        self.art: list[dict] = []
        self.seen: set[str] = set()
        self.profile: tuple[str, str] | None = None
        self.next_slide_at = 0.0

    def tick(self) -> None:
        """Publish the next slide on interval lapse or profile change."""
        now = time.monotonic()
        if (
            now < self.next_slide_at and self._config() == self.profile
        ) or self._paused():
            return
        self._advance(now)

    def clear(self) -> None:
        """Clear all published slideshow props."""
        for key in PROPS:
            window_property(key)

    def _paused(self) -> bool:
        """True while fullscreen playback should freeze the slideshow."""
        return condition(
            "Window.IsVisible(fullscreenvideo) | Window.IsVisible(visualisation)"
        )

    def _advance(self, now: float) -> None:
        """
        Refill the batch on exhaustion or profile change, then publish
        one random slide and schedule the next.

        :param now: Monotonic timestamp from tick().
        """
        profile = self._config()
        if profile != self.profile or not self.art:
            self.profile = profile
            self._fetch_batch()
        self.next_slide_at = now + self._interval()
        if not self.art:
            return
        item = self.art.pop(random.randrange(len(self.art)))
        self.seen.add(item["fanart"])
        if slide := self._process(item):
            self._publish(slide)

    def _config(self) -> tuple[str, str]:
        """
        Resolve the active profile (source type, custom path).

        :return: Tuple of (type, path) for the current time of day.
        """
        sfx = self._active_suffix()
        stype = infolabel(f"Skin.String(slideshow{sfx}_source)").lower() or "global"
        path = infolabel(f"Skin.String(slideshow{sfx}_path)")
        return stype, path

    def _active_suffix(self) -> str:
        """
        Choose between the two slideshow profiles by start hour.
        Profile 2 only participates when its toggle is enabled.

        :return: "" for profile 1, "2" for profile 2.
        """
        if not condition("Skin.HasSetting(slideshow2)"):
            return ""
        hour = time.localtime().tm_hour
        start = self._timer_hour("slideshow_start", 6)
        alt = self._timer_hour("slideshow2_start", 20)
        in_alt = (alt > start and (hour >= alt or hour < start)) or (
            alt <= start and alt <= hour < start
        )
        return "2" if in_alt else ""

    @staticmethod
    def _timer_hour(setting: str, fallback: int) -> int:
        """
        Parse the hour from an "HH:00" timer skin string.

        :param setting: Skin string name.
        :param fallback: Hour to use when the setting is unset.
        :return: Hour 0-23.
        """
        value = infolabel(f"Skin.String({setting})")
        return to_int(value.split(":")[0], fallback) if value else fallback

    def _interval(self) -> int:
        """
        Read the user-selected slide interval.

        :return: Interval in seconds.
        """
        return to_int(
            infolabel("Skin.String(slideshow_interval)"),
            self.DEFAULT_INTERVAL,
        )

    def _fetch_batch(self) -> None:
        """
        Refill self.art from the active profile's source, preferring items
        not yet shown this cycle. Seen resets when a cycle completes.
        """
        stype, path = self.profile
        self.art = []
        if stype == "custom":
            if path:
                self._fetch_custom(path)
        else:
            self._fetch_library(self._art_types(stype))
        if self.art:
            fresh = [item for item in self.art if item["fanart"] not in self.seen]
            if not fresh:  # full cycle shown — start over
                self.seen.clear()
                fresh = self.art
            self.art = fresh
        if len(self.art) > self.BATCH_SIZE:
            self.art = random.sample(self.art, self.BATCH_SIZE)
        log.debug(f"{self.__class__.__name__}: Fetched {len(self.art)} items")

    def _art_types(self, stype: str) -> list[str]:
        """
        Map a source type to library query targets, filtered by content presence.

        :param stype: Source type from skin settings.
        :return: List of JSON-RPC method suffixes (e.g. "movies", "artists").
        """
        return [
            self.LIBRARY_MAP[key]
            for key in self.TYPE_MAP.get(stype, (stype,))
            if key in self.LIBRARY_MAP and condition(f"Library.HasContent({key})")
        ]

    def _fetch_library(self, art_types: list[str]) -> None:
        """
        Fetch random art batches from the video/music libraries.

        :param art_types: Library targets from _art_types().
        """
        for art_type in art_types:
            dbtype = "Audio" if art_type == "artists" else "Video"
            query = json_call(
                f"{dbtype}Library.Get{art_type}",
                properties=["art"],
                sort={"method": "random"},
                limit=self.BATCH_SIZE,
                parent="slideshow_fetch",
            )
            self.art.extend(
                {"title": result.get("label", ""), **result["art"]}
                for result in query.get("result", {}).get(art_type, [])
                if result.get("art", {}).get("fanart")
            )

    def _fetch_custom(self, path: str) -> None:
        """
        Fetch art from a user path (library node, xsp, plugin, folder)
        in a single directory listing with art properties.

        :param path: Custom source path from skin settings.
        """
        query = json_call(
            "Files.GetDirectory",
            params={"directory": path, "properties": ["art"]},
            sort={"method": "random"},
            limit=self.BATCH_SIZE,
            parent="slideshow_fetch",
        )
        for result in query.get("result", {}).get("files", []):
            art = result.get("art", {})
            if fanart := art.get("fanart") or art.get("thumb"):
                self.art.append(
                    {"title": result.get("label", ""), **art, "fanart": fanart}
                )

    def _process(self, item: dict) -> dict | None:
        """
        Blur and darken the fanart and crop the clearlogo through the
        shared cache. Background opts come from skin-declared params prop.

        :param item: Art dict from the fetch batch.
        :return: Slide dict with fanart/blur/darken/clearlogo/title, or None.
        """
        fanart = self._fanart_url(item)
        if not fanart:
            return None
        clearlogo = item.get("clearlogo-billboard") or item.get("clearlogo")
        params = dict(
            parse_qsl(infolabel("Window(home).Property(slideshow_artwork_params)"))
        )
        params["background_url"] = fanart
        if "background_blur" not in params:  # declaration absent: plain blur
            params["background_blur"] = "true"
        art_opts = {"background": ArtOpts.from_params(params, "background")}
        jobs: dict[str, tuple[str, ...]] = {"background": ("blur", "darken")}
        if clearlogo:
            art_opts["clearlogo"] = ArtOpts(
                url=url_decode_path(clearlogo),
                crop=True,
                blur=False,
                analyze=False,
                blur_radius=None,
                darken=None,
            )
            jobs["clearlogo"] = ("crop",)
        processed = self.image_processor(jobs=jobs, art_opts=art_opts)
        if not (blur := processed.get("background")):
            return None
        darken = processed.get("background_darken")
        return {
            "fanart": fanart,
            "blur": blur,
            "clearlogo": processed.get("clearlogo"),
            "darken": str(darken) if darken is not None else None,
            "title": item.get("title", ""),
        }

    @staticmethod
    def _fanart_url(item: dict) -> str | None:
        """
        Pick a random fanart from the item's art set (multiart included)
        and normalise the URL.

        :param item: Art dict from the fetch batch.
        :return: Decoded fanart path, or None.
        """
        fanarts = [value for key, value in item.items() if "fanart" in key]
        if not fanarts:
            return None
        fanart = random.choice(fanarts)
        if "transform?size=thumb" in fanart:
            fanart = fanart[:-21]
        return url_decode_path(fanart)

    def _publish(self, slide: dict) -> None:
        """
        Write the slide to window props. clearlogo may be None, which
        clears the prop via window_property's falsy handling.

        :param slide: Slide dict from _process().
        """
        window_property("slideshow_fanart", value=slide["fanart"])
        window_property("slideshow_blur", value=slide["blur"])
        window_property("slideshow_darken", value=slide["darken"])
        window_property("slideshow_clearlogo", value=slide["clearlogo"])
        window_property("slideshow_title", value=slide["title"])
