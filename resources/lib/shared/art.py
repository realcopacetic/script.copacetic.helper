# author: realcopacetic

import random
import time
from functools import wraps

from PIL import Image, ImageFilter

from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    TEMPS,
    Path,
    condition,
    infolabel,
    json_call,
    log,
    url_decode_path,
    validate_path,
    window_property,
    xbmc,
    xbmcvfs,
)


class ImageEditor:
    """
    Handles cropping, blurring, and metadata extraction for artwork images.
    Uses PIL to process images and manages caching via SQLite.
    """

    def __init__(self, sqlite_handler=None):
        """
        Initializes the editor and sets default processing parameters.

        :param sqlite_handler: Optional SQLiteHandler instance for caching.
        """
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.clearlogo_bbox = (600, 240)
        self.blur_bbox = (480, 270)
        self.temp_folder = TEMPS

    def image_processor(self, dbid=None, source=None, processes=None, url=None):
        """
        Coordinates image processing tasks and returns metadata and paths.

        :param dbid: Optional DB ID for the item.
        :param source: Source of artwork, e.g. Container.ListItem.
        :param processes: Dict of art_type → process type (e.g., crop, blur).
        :param url: Optional direct artwork URL.
        :returns: Dict of processed paths and metadata.
        """
        if not processes:
            return {}

        log(
            ", ".join(
                f"{self.__class__.__name__}: Processing {key}: {value} for {processes}"
                for key, value in {"dbid": dbid, "url": url}.items()
                if value
            )
        )

        try:
            attributes = [
                self._handle_image(
                    source=source,
                    url=url,
                    art_type=art_type,
                    process=process,
                )
                for art_type, process in processes.items()
            ]
        except Exception as error:
            log(
                f"{self.__class__.__name__}: Error during SQL write → {error}",
                force=True,
            )
            return {}

        return {
            (
                f"{attr['category']}_{key}"
                if key in ["color", "luminosity"]
                else attr["category"]
            ): attr[key]
            for attr in attributes
            if attr
            for key in ["processed", "color", "luminosity"]
            if attr.get(key) is not None
        }

    def _handle_image(
        self,
        source="Container.ListItem",
        url=False,
        art_type="clearlogo",
        process="crop",
    ):
        """
        Retrieves or processes a single image and writes it to the lookup table.

        :returns: Metadata dict or None.
        """
        if not (
            art := {art_type: url} if url else self._fetch_art_url(source, art_type)
        ):
            return None

        attributes = self._read_lookup(art) or (
            process_method(art)
            if (process_method := getattr(self, f"_{process}_art", None))
            else None
        )
        self._write_lookup(art_type, attributes)
        return attributes

    def _fetch_art_url(self, source, art_type):
        """
        Retrieves artwork URL via infolabel if not provided directly.

        :returns: Dict containing artwork URL or False.
        """
        if not self._wait_for_art():
            return {art_type: False}
        return {art_type: infolabel(f"{source}.Art({art_type})")}

    def _wait_for_art(self):
        """
        Waits briefly for Kodi to populate artwork if needed.

        :returns: True if art is ready, else False.
        """
        timeout = time.time() + 2

        if not condition("String.IsEmpty(Window(home).Property(art_loaded))"):
            return True  # Art is already loaded, no need to wait

        while time.time() < timeout:
            if condition("!String.IsEmpty(Control.GetLabel(6010))"):
                window_property("art_loaded", value="true")
                return True
            xbmc.Monitor().waitForAbort(0.02)  # Wait for 20ms before retrying

        return False

    def _read_lookup(self, art):
        """
        Reads processed metadata from the SQLite lookup cache.

        :returns: Cached metadata dict or None.
        """
        url = next(iter(art.values()), None)
        return (
            attributes
            if (
                url
                and (attributes := self.sqlite.get_entry(url))
                and validate_path(attributes.get("processed"))
            )
            else None
        )

    def _write_lookup(self, art_type, attributes):
        """
        Writes metadata into the SQLite cache.

        :returns: None
        """
        if attributes:
            self.sqlite.add_entry(
                "clearlogo" if "clearlogo" in art_type else art_type, attributes
            )

    def _process_image(folder, extension):
        """
        Decorator that wraps a process method to handle PIL image I/O.

        :param folder: Destination folder for saved image.
        :param extension: Output file extension.
        :returns: Wrapped image processor method.
        """
        def decorator(process_func):
            @wraps(process_func)
            def wrapper(self, art):
                if not art:
                    return None

                category, url = next(iter(art.items()), (None, None))
                if not url:
                    return None

                source, destination = self._generate_image_urls(folder, url, extension)
                if not (image := self._image_open(source)):
                    return None

                start_time = time.perf_counter()
                result = process_func(self, image)
                end_time = time.perf_counter()

                if not result or "image" not in result:
                    return None

                with xbmcvfs.File(destination, "wb") as f:
                    result["image"].save(f, result.get("format", "PNG"))
                    log(
                        f"{self.__class__.__name__}: File processed: {url} → {destination}"
                    )
                if self.temp_folder in source:  # If temp file created, delete it
                    xbmcvfs.delete(source)
                    log(f"{self.__class__.__name__}: Temp file deleted → {source}")
                log(
                    f"{self.__class__.__name__}: Processing time: {end_time - start_time:.3f} seconds"
                )
                return {
                    "category": category,
                    "url": url,
                    "processed": destination,
                    **result.get("metadata", {}),
                }

            return wrapper

        return decorator

    @_process_image(folder=BLURS, extension=".jpg")
    def _blur_art(self, image):
        """
        Applies Gaussian blur and resizes to blur bounding box.

        :returns: Dict with processed PIL image and format info.
        """
        image.thumbnail(self.blur_bbox, Image.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(radius=50))
        return {"image": image, "format": "JPEG"}

    @_process_image(folder=CROPS, extension=".png")
    def _crop_art(self, image):
        """
        Crops and resizes clearlogos, returns color and luminosity metadata.

        :returns: Dict with image, format, and metadata.
        """
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        pre_resize_max = (1840, 713)
        if image.width > pre_resize_max[0] or image.height > pre_resize_max[1]:
            image.thumbnail(pre_resize_max, Image.LANCZOS)

        try:
            image = image.crop(image.convert("RGBA").getbbox())
        except ValueError as error:
            log(
                f"{self.__class__.__name__}: Error - unsupported mode {image.mode} → {error}",
                force=True,
            )
            return None

        final_max = (1600, 620)
        if image.width > final_max[0] or image.height > final_max[1]:
            image.thumbnail(final_max, Image.LANCZOS)

        color, luminosity = self._color_functions(image)

        return {
            "image": image,
            "format": "PNG",
            "metadata": {"color": color, "luminosity": luminosity},
        }

    def _generate_image_urls(self, folder, url, suffix):
        """
        Determines source and destination paths for processed artwork.

        :returns: Tuple of (source_path, destination_path).
        """
        decoded_url = url_decode_path(url)
        cached_thumb = self._get_cached_thumb(decoded_url, suffix)
        source_url = (
            Path(f"special://profile/Thumbnails/{cached_thumb[0]}") / cached_thumb
        )
        destination_url = Path(folder) / cached_thumb

        return (
            (source_url, destination_url)
            if validate_path(source_url)
            else (self._create_temp_file(decoded_url, cached_thumb), destination_url)
        )

    def _create_temp_file(self, url, cached_thumb):
        """
        Copies original image to temp folder if no cache exists.

        :returns: Path to the temp file.
        """
        temp_url = Path(self.temp_folder) / cached_thumb
        if not validate_path(temp_url) and xbmcvfs.copy(url, temp_url):
            log(f"{self.__class__.__name__}: Temporary file created → {temp_url}")
        return temp_url

    def _color_functions(self, image):
        """
        Extracts dominant color and computes perceived luminosity.

        :returns: Tuple of (hex color, luminosity as int).
        """
        try:
            small_image = image.copy()
            small_image.thumbnail((25, 10))
            pixeldata = small_image.getcolors(250)  # 25 * 10
            small_image.close()
        except Exception as e:
            log(f"{self.__class__.__name__}: Error processing colors: {e}", force=True)
            return "ff000000", "0"

        # Extract opaque pixels, sort by occurrence
        opaque_pixels = [
            color
            for count, color in sorted(pixeldata or [], reverse=True)
            if color[-1] > 64  # Filter out low-opacity pixels
        ]

        if not opaque_pixels:
            log(
                f"{self.__class__.__name__}: Error - No opaque pixels found", force=True
            )
            return "ff000000", "0"

        # Create palette from opaque pixels
        try:
            paletted = Image.new("RGBA", (len(opaque_pixels), 1))
            paletted.putdata(opaque_pixels)
            paletted = paletted.convert("P", palette=Image.ADAPTIVE, colors=16)
            palette = paletted.getpalette()
            dominant_index = max(paletted.getcolors(), key=lambda x: x[0])[1]
            paletted.close()
        except Exception as e:
            log(f"{self.__class__.__name__}: Palette error {e}", force=True)
            return "ff000000", "0"

        dominant_rgb = tuple(palette[dominant_index * 3 : dominant_index * 3 + 3])

        return self._rgb_to_hex(dominant_rgb), int(
            self._return_luminosity(dominant_rgb) * 1000
        )

    @staticmethod
    def _get_cached_thumb(url, suffix):
        """
        Returns cache-safe filename from a URL with given extension.

        :returns: Cached filename string.
        """
        return xbmc.getCacheThumbName(url).replace(".tbn", f"{suffix}")

    @staticmethod
    def _image_open(url):
        """
        Attempts to open an image using PIL from a Kodi VFS path.

        :returns: PIL Image or None on failure.
        """
        try:
            return Image.open(xbmcvfs.translatePath(url))
        except (FileNotFoundError, OSError) as error:
            log(
                f"{__class__.__name__}: Error - Cannot open image {url} → {error}",
                force=True,
            )
            return None

    @staticmethod
    def _return_luminosity(rgb):
        """
        Calculates perceived brightness of an RGB color.
        https://stackoverflow.com/questions/3942878/how-to-decide-font-color-in-white-or-black-depending-on-background-color
        :returns: Float between 0 and 1.
        """
        def linearize(channel):
            c = channel / 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = map(linearize, rgb[:3])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @staticmethod
    def _rgb_to_hex(rgb):
        """
        Converts an RGB tuple into a hex string with ff prefix.

        :returns: ARGB hex string.
        """
        r, g, b = rgb[:3]
        return f"ff{r:02x}{g:02x}{b:02x}"


class SlideshowMonitor:
    """
    Manages dynamic background artwork for slideshows in Kodi.
    Supports videodb, musicdb and custom user sources.
    """
    MAX_FETCH_COUNT = 20

    def __init__(self, sqlite_handler=None):
        """
        Initializes the slideshow with optional SQLite and processing tools.

        :param sqlite_handler: Optional SQLiteHandler instance.
        """
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor
        self.slideshow_path = self._get_slideshow_path()
        self.slideshow_source = self._check_slideshow_source()
        self.fetch_count = 0
        self.art = []

    def background_slideshow(self, art_type=None):
        """
        Main method for updating artwork slideshow periodically for use in Kodi.

        :param art_type: Optional content type ("movies", "music", etc.).
        """
        self.art_type = art_type or "global"
        content_map = {"movies": "movies", "tvshows": "tvshows", "music": "artists"}

        self.art_types = (
            [
                content_map[k]
                for k in content_map
                if condition(f"Library.HasContent({k})")
            ]
            if self.art_type == "global"
            else (
                [
                    content_map[k]
                    for k in ["movies", "tvshows"]
                    if condition(f"Library.HasContent({k})")
                ]
                if self.art_type == "videos"
                else (
                    ["custom"]
                    if self.art_type == "custom"
                    else (
                        [content_map.get(self.art_type, self.art_type)]
                        if condition(f"Library.HasContent({self.art_type})")
                        else []
                    )
                )
            )
        )

        new_path, new_source = (
            self._get_slideshow_path(),
            self._check_slideshow_source(),
        )

        if (
            self.fetch_count == 0
            or not self.art
            or new_path != self.slideshow_path
            or new_source != self.slideshow_source
        ):
            self.slideshow_path, self.slideshow_source = new_path, new_source
            log(f"{self.__class__.__name__}: Fetching background art")
            self._get_art()

        self.fetch_count = (self.fetch_count + 1) % self.MAX_FETCH_COUNT
        self._set_art()

    def _get_art(self):
        """Fetches new artwork based on content type and source."""
        if not self.art_types:
            log(
                f"{self.__class__.__name__}: No slideshow artwork available, skipping fetch"
            )
            return

        self.art = []

        if "custom" in self.art_type:
            if not self.slideshow_path:
                log(
                    f"{self.__class__.__name__}: No custom slideshow path found, skipping fetch"
                )
                return

            # Fetch plugin art
            if "library" not in self.slideshow_source and condition(
                "Integer.IsGreater(Container(3300).NumItems,0)"
            ):
                log(f"{self.__class__.__name__}: Fetching plugin art")
                self._get_plugin_art()
                return

            # Fetch custom library art
            log(
                f"{self.__class__.__name__}: Fetching library art from {self.slideshow_path}"
            )
            query = json_call(
                "Files.GetDirectory",
                params={"directory": self.slideshow_path},
                sort={"method": "random"},
                limit=self.MAX_FETCH_COUNT,
                parent="get_directory",
            )
            for result in query.get("result", {}).get("files", []):
                item_type, item_id = result.get("type"), result.get("id")
                dbtype = "Video" if item_type != "artist" else "Audio"
                details_query = json_call(
                    f"{dbtype}Library.Get{item_type}Details",
                    params={"properties": ["art"], f"{item_type}id": item_id},
                    parent="get_item_details",
                )
                item_details = details_query.get("result", {}).get(
                    f"{item_type}details", {}
                )
                if (art_data := item_details.get("art", {})).get("fanart"):
                    self.art.append(
                        {"title": item_details.get("label", ""), **art_data}
                    )

        # Fetch predefined library art
        else:
            log(f"{self.__class__.__name__}: Fetching predefined library artwork")
            for art_type in self.art_types:
                dbtype = "Video" if art_type != "artists" else "Audio"
                query = json_call(
                    f"{dbtype}Library.Get{art_type}",
                    properties=["art"],
                    sort={"method": "random"},
                    limit=self.MAX_FETCH_COUNT,
                    parent="get_art",
                )
                self.art.extend(
                    {"title": result.get("label", ""), **result["art"]}
                    for result in query.get("result", {}).get(art_type, [])
                    if result.get("art", {}).get("fanart")
                )

        if len(self.art) > self.MAX_FETCH_COUNT:
            self.art = random.sample(self.art, self.MAX_FETCH_COUNT)
        log(
            (
                f"{self.__class__.__name__}: Total artwork found: {len(self.art)}"
                if self.art
                else f"{self.__class__.__name__}: WARNING - No artwork was found!"
            ),
            force=not self.art,
        )

    def _get_plugin_art(self):
        """Fetches artwork directly from plugin containers (e.g., widgets)."""
        num_items = int(infolabel("Container(3300).NumItems"))
        self.art.extend(
            {
                "title": infolabel(f"Container(3300).ListItem({i}).Label"),
                "fanart": fanart,
                "clearlogo": infolabel(f"Container(3300).ListItem({i}).Art(clearlogo)"),
            }
            for i in range(num_items)
            if (fanart := infolabel(f"Container(3300).ListItem({i}).Art(fanart)"))
            or (
                "folder" in (self.slideshow_source or "")
                and (fanart := infolabel(f"Container(3300).ListItem({i}).Art(thumb)"))
            )
        )

    def _get_slideshow_path(self):
        """
        Determines the correct slideshow path based on time of day.

        :returns: String path from skin setting.
        """
        current_hour = time.localtime().tm_hour
        start = int(infolabel("Skin.String(slideshow_start)") or 6)
        alt_start = int(infolabel("Skin.String(alt_slideshow_start)") or 20)

        is_alt_slideshow = (
            alt_start > start and (current_hour >= alt_start or current_hour < start)
        ) or (alt_start <= start and start > current_hour >= alt_start)

        slideshow_prefix = "alt_" if is_alt_slideshow else ""
        return infolabel(f"Skin.String({slideshow_prefix}slideshow_path)")

    def _check_slideshow_source(self):
        """
        Identifies whether slideshow source is a folder, plugin, or library.

        :returns: Source type string.
        """
        if "plugin://" in self.slideshow_path:
            return "plugin"
        return (
            "library"
            if any(
                x in self.slideshow_path
                for x in ("db://", "library://", ".xsp", ".xml")
            )
            else "folder"
        )

    def _set_art(self):
        """
        Selects and displays the next random fanart + optional clearlogo,
        writing these values to window properties for use within Kodi.
        """
        if not self.art:
            log(
                f"{self.__class__.__name__}: No art available, waiting for next fetch",
                force=True,
            )
            return

        def get_fanart(art):
            fanart = next((art.get(k) for k in art if "fanart" in k), None)
            return (
                url_decode_path(fanart[:-21])
                if "transform?size=thumb" in fanart
                else url_decode_path(fanart)
            )

        def process_clearlogo(clearlogo):
            if not clearlogo:
                return None

            processed = self.image_processor(
                url=url_decode_path(clearlogo),
                processes={
                    (
                        "clearlogo-billboard"
                        if "billboard" in clearlogo
                        else "clearlogo"
                    ): "crop"
                },
            )
            return (
                processed.get("clearlogo-billboard") or processed.get("clearlogo")
                if processed
                else None
            )

        art = self.art.pop(random.randrange(len(self.art)))
        fanart = get_fanart(art)
        clearlogo = process_clearlogo(
            art.get("clearlogo-billboard") or art.get("clearlogo")
        )

        for key, value in {
            "slideshow_fanart": fanart,
            "slideshow_clearlogo": clearlogo,
            "slideshow_title": art.get("title"),
        }.items():
            window_property(key, value=value)
