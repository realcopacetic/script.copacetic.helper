# author: realcopacetic

import random
import time
from urllib.parse import parse_qsl, quote

from resources.lib.art import policy
from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
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
    "slideshow_slot",
    "slideshow_clearlogo_a",
    "slideshow_title_a",
    "slideshow_clearlogo_b",
    "slideshow_title_b",
)


class Slideshow:
    """
    Global background slideshow. Publishes one prop set per slide (fanart, blur,
    cropped clearlogo, title; logo and title again in alternating slots) on a
    fixed interval; all transition presentation is owned by the skin.
    """

    BATCH_SIZE = 20
    CUSTOM_WINDOW = 200  # a listing's limit comes before the art test: sample from more
    DEFAULT_INTERVAL = 5
    LIBRARY_PATHS = ("videodb://", "musicdb://", "library://")  # or .xsp: art per item
    RETRY_WITHIN = 1  # seconds: a slower failed slide (a dead share) waits the interval

    LIBRARY_MAP = {"movies": "movies", "tvshows": "tvshows", "music": "artists"}
    TYPE_MAP = {
        "global": ("movies", "tvshows", "music"),
        "videos": ("movies", "tvshows"),
        "artists": ("music",),
    }
    # Kodi's own picture extensions, less the archive and feed types
    PICTURE_EXTENSIONS = (
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".gif",
        ".ico",
        ".tif",
        ".tiff",
        ".tga",
        ".pcx",
        ".webp",
        ".jp2",
        ".apng",
        ".avif",
    )

    def __init__(self) -> None:
        """Initialise processing pipeline and scheduling state."""
        self.image_processor = ImageEditor().image_processor
        self.art = []
        self.seen = set()
        self.profile = None
        self.next_slide_at = 0.0
        self.slot = infolabel("Window(home).Property(slideshow_slot)") or "b"
        self.shown = None  # the current slide's (item, fanart)
        self.query = ""  # the params its darken was measured by

    def tick(self) -> None:
        """
        Publish the next slide on interval lapse or profile change; when only the
        skin's params change, republish the current slide's darken.
        """
        due = time.monotonic() >= self.next_slide_at or self._config() != self.profile
        query = infolabel("Window(home).Property(slideshow_artwork_params)")
        if not (due or (self.shown and query != self.query)) or self._paused():
            return
        if due:
            self._advance(query)
        else:
            self._redarken(query)

    def clear(self) -> None:
        """Clear all published slideshow props."""
        for key in PROPS:
            window_property(key)

    def _paused(self) -> bool:
        """True while fullscreen playback should freeze the slideshow."""
        return condition(
            "Window.IsVisible(fullscreenvideo) | Window.IsVisible(visualisation)"
        )

    def _advance(self, query: str) -> None:
        """
        Refill the batch on exhaustion or profile change, then publish one random
        slide and schedule the next from after the fetch. A slide that fails within
        RETRY_WITHIN tries another item next tick; a slower one waits after it.

        :param query: The skin's slideshow_artwork_params.
        """
        profile = self._config()
        if profile != self.profile or not self.art:
            self.profile = profile
            self._fetch_batch()
        interval = self._interval()
        start = time.monotonic()  # after the fetch: a slow source eats no interval
        self.next_slide_at = start + interval
        if not self.art:
            return
        item = self.art.pop(random.randrange(len(self.art)))
        self.seen.add(item["fanart"])
        fanart = self._fanart_url(item)
        with log.muted():
            if slide := self._process(item, fanart, query):
                self._publish(slide)
                self.shown, self.query = (item, fanart), query
            elif (end := time.monotonic()) - start >= self.RETRY_WITHIN:
                self.next_slide_at = end + interval  # rest a whole interval after it
            elif self.art:
                self.next_slide_at = start

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
        log.debug(f"{self.__class__.__name__} → Fetched {len(self.art)} items")

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
        Fetch art from a user path (library node, xsp, plugin, folder) in a
        single directory listing. A picture file with no art is its own fanart.
        Outside the library, more entries are listed than a batch needs.

        :param path: Custom source path from skin settings.
        """
        library = path.startswith(self.LIBRARY_PATHS) or path.lower().endswith(".xsp")
        query = json_call(
            "Files.GetDirectory",
            params={"directory": path, "properties": ["art"]},
            sort={"method": "random"},
            limit=self.BATCH_SIZE if library else self.CUSTOM_WINDOW,
            parent="slideshow_fetch",
        )
        for result in query.get("result", {}).get("files", []):
            art, file = result.get("art", {}), result["file"]
            picture = file.lower().endswith(self.PICTURE_EXTENSIONS) and (
                f"image://{quote(file, safe='')}/"  # wrapped like Kodi's own art
            )
            if fanart := art.get("fanart") or art.get("thumb") or picture:
                self.art.append(
                    {"title": result.get("label", ""), **art, "fanart": fanart}
                )

    def _process(self, item: dict, fanart: str | None, query: str) -> dict | None:
        """
        Blur and darken the fanart and crop and measure the clearlogo through the
        shared cache. Background opts come from the skin-declared params.

        :param item: Art dict from the fetch batch.
        :param fanart: Fanart URL picked from the item's art set.
        :param query: The skin's slideshow_artwork_params.
        :return: Slide dict with fanart/blur/darken/clearlogo/title, or None.
        """
        if not fanart:
            return None
        clearlogo = item.get("clearlogo-billboard") or item.get("clearlogo")
        params = dict(parse_qsl(query))
        params["background_url"] = fanart
        if "background_blur" not in params:  # declaration absent: plain blur
            params["background_blur"] = "true"
        art_opts = {"background": ArtOpts.from_params(params, "background")}
        jobs = {"background": policy.ART_PROCESS_MAP["background"]}
        if clearlogo:
            art_opts["clearlogo"] = ArtOpts.from_params(
                {"clearlogo_url": clearlogo, "clearlogo_crop": "true"},
                "clearlogo",
            )
            jobs["clearlogo"] = policy.ART_PROCESS_MAP["clearlogo"]  # crop and colour
        processed = self.image_processor(jobs=jobs, art_opts=art_opts)
        if not (blur := processed.get("background")):
            return None
        darken = processed.get("background_darken")
        return {
            "fanart": url_decode_path(fanart),  # a multiimage needs the plain path
            "blur": blur,
            "clearlogo": processed.get("clearlogo"),
            "darken": str(darken) if darken is not None else None,
            "title": item.get("title", ""),
        }

    @staticmethod
    def _fanart_url(item: dict) -> str | None:
        """
        Pick a random fanart from the item's art (multiart and a parent show's or
        artist's included, not its movie set's), the whole picture for a picture's
        thumb. Left wrapped: the cache decodes it once.

        :param item: Art dict from the fetch batch.
        :return: Fanart URL as JSON-RPC wraps art, or None.
        """
        fanarts = [
            value
            for key, value in item.items()
            if "fanart" in key and not key.startswith("set.")
        ]
        if not fanarts:
            return None
        return random.choice(fanarts).removesuffix("transform?size=thumb")

    def _redarken(self, query: str) -> None:
        """
        Republish the current slide's darken by new params, through the same cached
        serve; its fanart, blur, logo, title and slot stay as published.

        :param query: The skin's slideshow_artwork_params.
        """
        self.query = query
        with log.muted():
            if slide := self._process(*self.shown, query):
                window_property("slideshow_darken", value=slide["darken"])

    def _publish(self, slide: dict) -> None:
        """
        Write the slide to window props, then its clearlogo and title to the idle
        slot and flip slideshow_slot to it last, so the skin still holds the
        outgoing pair. Falsy values clear their prop.

        :param slide: Slide dict from _process().
        """
        self.slot = "a" if self.slot == "b" else "b"
        for key in ("fanart", "blur", "darken", "clearlogo", "title"):
            window_property(f"slideshow_{key}", value=slide[key])
        for key in ("clearlogo", "title"):
            window_property(f"slideshow_{key}_{self.slot}", value=slide[key])
        window_property("slideshow_slot", value=self.slot)
