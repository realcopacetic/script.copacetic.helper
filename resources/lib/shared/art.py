# author: realcopacetic

import random
import time

from PIL import Image, ImageFilter

from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (BLUR_FOLDERPATH, CROP_FOLDERPATH,
                                            TEMP_FOLDERPATH, condition, infolabel,
                                            json_call, log, os, url_decode_path,
                                            validate_path, window_property, xbmc,
                                            xbmcvfs)


class ImageEditor:
    def __init__(self, sqlite_handler=None):
        self.sqlite = sqlite_handler if sqlite_handler else SQLiteHandler()
        self.clearlogo_bbox = (600, 240)
        self.blur_bbox = (480, 270)
        self.blur_folder = BLUR_FOLDERPATH
        self.crop_folder = CROP_FOLDERPATH
        self.temp_folder = TEMP_FOLDERPATH

    def image_processor(self, dbid=False, source=False, processes=False, url=False):
        if dbid:
            log(
                f"ImageEditor: Processing image for dbid: {dbid}, source: {source}, processes: {processes}")
        if url:
            log(
                f"ImageEditor: Processing image for url: {url}, processes: {processes}")
        attributes = []
        art = {}
        try:
            for art_type, process in processes.items():
                current_attributes = self._handle_image(
                    dbid=dbid, source=source, url=url, art_type=art_type, process=process)
                attributes.append(current_attributes)
        except Exception as error:
            log(f"ImageEditor: Error during SQL write --> {error}", force=True)
        else:
            for attribute in attributes:
                if not attribute:  # Skip if attribute is None
                    continue
                try:
                    if attribute["processed"]:
                        art[f'{attribute["category"]}'] = attribute["processed"]
                    for key in ["color", "luminosity"]:
                        value = attribute.get(key)
                        if value is not None:
                            art[f'{attribute["category"]}_{key}'] = value
                except (TypeError, KeyError):
                    continue  # Skip empty attributes
            return art

    def _handle_image(self, dbid=False, source="Container.ListItem", url=False, art_type="clearlogo", process="crop"):
        # fetch art url
        art = {art_type: url} if url else self._fetch_art_url(
            source, art_type)
        if art:
            # check for processed art in lookup table
            attributes = self._read_lookup(art)
            # or process and write to lookup if missing
            if not attributes:
                process_method = getattr(self, f"_{process}_art", None)
                attributes = process_method(art)
                self._write_lookup(art_type, attributes)
            return attributes

    def _fetch_art_url(self, source, art_type):
        art = {art_type: False}
        if self._wait_for_art():
            art[art_type] = infolabel(f"{source}.Art({art_type})")
            return art

    def _wait_for_art(self):
        timeout = time.time() + 3  # Set a timeout 2s in the future
        while time.time() < timeout:
            if condition("!String.IsEmpty(Control.GetLabel(6010))"):
                return True
            xbmc.Monitor().waitForAbort(0.05)  # Wait for 50ms before retrying
        return False

    def _read_lookup(self, art):
        url = list(art.values())[0] if art else None
        if not url:
            return None
        attributes = self.sqlite.get_entry(url)
        return attributes if attributes and validate_path(attributes["processed"]) else None

    def _write_lookup(self, art_type, attributes):
        #   writes processed image data to JSON
        if attributes:
            art_type = "clearlogo" if "clearlogo" in art_type else art_type
            self.sqlite.add_entry(art_type, attributes)

    def _blur_art(self, art):
        def blur(image):
            start_time = time.perf_counter()  # Start timing
            image.thumbnail(self.blur_bbox, Image.LANCZOS)
            image = image.filter(ImageFilter.GaussianBlur(radius=50))
            end_time = time.perf_counter()  # Stop timing
            log(f"ImageEditor: Blur time: {end_time - start_time:.6f} seconds")
            return {
                "image": image,
                "format": "JPEG"
            }
        return self._process_image(self.blur_folder, art, ".jpg", blur)

    def _crop_art(self, art):
        def crop(image):
            start_time = time.perf_counter()  # Start timing
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            # Resize large images before cropping to reduce processing time
            width, height = image.size
            if width > 1840 or height > 713:
                image.thumbnail((1840, 713), Image.LANCZOS)
            # crop using alpha channel
            try:
                image = image.crop(image.convert("RGBA").getbbox())
            except ValueError as error:
                log(
                    f"ImageEditor: Error - could not convert image due to unsupported mode {image.mode} --> {error}", force=True)
                return None
            # Resize image to max 1600 x 620, 2x standard kodi size of 800x310
            width, height = image.size
            if width > 1600 or height > 620:
                image.thumbnail((1600, 620), Image.LANCZOS)
            color, luminosity = self._image_functions(image)
            end_time = time.perf_counter()  # Stop timing
            log(f"ImageEditor: Crop time: {end_time - start_time:.6f} seconds")
            return {
                "image": image,
                "format": "PNG",
                "metadata": {"color": color, "luminosity": luminosity}
            }
        return self._process_image(self.crop_folder, art, ".png", crop)

    def _process_image(self, folder, art, extension, process_func):
        art = list(art.items())[0]
        url = art[1]
        source_url, destination_url = self._generate_image_urls(
            folder, url, extension)
        try:
            image = self._image_open(source_url)
        except Exception as error:
            log(
                f"ImageEditor: Error - could not open cached image --> {error}", force=True)
            return None
        else:
            result = process_func(image)
            with xbmcvfs.File(destination_url, "wb") as f:
                result["image"].save(f, result.get("format", "PNG"))
                log(
                    f"ImageEditor: Image processed and saved: {url} --> {destination_url}")
                if self.temp_folder in source_url:  # If temp file created, delete it now
                    xbmcvfs.delete(source_url)
                    log(
                        f"ImageEditor: Temporary file deleted --> {source_url}")
            return {
                "category": art[0],
                "url": url,
                "processed": destination_url,
                # Merge additional metadata if available
                **result.get("metadata", {})
            }

    def _get_cached_thumb(self, url, suffix):
        # use source url to generate cached url
        cached_thumb = xbmc.getCacheThumbName(url).replace(".tbn", f"{suffix}")
        return cached_thumb

    def _generate_image_urls(self, folder, url, suffix):
        decoded_url = url_decode_path(url)
        cached_thumb = self._get_cached_thumb(decoded_url, suffix)
        source_url = os.path.join(
            f"special://profile/Thumbnails/{cached_thumb[0]}/", cached_thumb
        )
        destination_url = os.path.join(folder, cached_thumb)
        if validate_path(source_url):
            return source_url, destination_url
        else:
            source_url = self._create_temp_file(decoded_url, cached_thumb)
            return source_url, destination_url

    def _create_temp_file(self, url, cached_thumb):
        # create temp file from original url
        temp_url = os.path.join(self.temp_folder, cached_thumb)
        if not validate_path(temp_url):
            xbmcvfs.copy(url, temp_url)
            log(f"ImageEditor: Temporary file created --> {temp_url}")
        return temp_url

    def return_luminosity(self, rgb):
        # Credit to Mark Ransom for luminosity calculation
        # https://stackoverflow.com/questions/3942878/how-to-decide-font-color-in-white-or-black-depending-on-background-color
        # Take only the first 3 channels in case there are more (e.g., RGBA)
        new_rgb = ()
        for channel in rgb[:3]:  # Slice to get only R, G, B channels
            c = channel / 255.0
            if c <= 0.04045:
                output = c / 12.92
            else:
                output = pow(((c + 0.055) / 1.055), 2.4)
            new_rgb += (output,)
        r, g, b = new_rgb
        luminosity = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return luminosity

    def _image_open(self, url):
        image = Image.open(xbmcvfs.translatePath(url))
        return image

    def _image_functions(self, image):
        width, height = 25, 10
        small_image = image.copy()
        try:
            small_image.thumbnail((width, height))
            pixeldata = small_image.getcolors(width * height)
        finally:
            small_image.close()
        # Remove transparent pixels
        sorted_pixeldata = sorted(pixeldata, key=lambda t: t[0], reverse=True)
        opaque_pixeldata = [p for p in sorted_pixeldata if p[-1][-1] > 64]
        opaque_pixels = [color for count,
                         color in opaque_pixeldata for _ in range(count)]
        if not opaque_pixeldata:
            log("ImageEditor: Error - No opaque pixels found for calculation of dominant colour and luminosity", force=True)
            return ("ff000000", "0")
        else:
            # Create a palette directly from the opaque pixels
            paletted = Image.new("RGBA", (len(opaque_pixels), 1))
            try:
                paletted.putdata(opaque_pixels)
                paletted = paletted.convert(
                    "P", palette=Image.ADAPTIVE, colors=16)
                # Find color that occurs most often
                palette = paletted.getpalette()
                color_counts = sorted(paletted.getcolors(), reverse=True)
                try:
                    palette_index = color_counts[0][1]
                except IndexError as error:
                    log(
                        f"ImageEditor: Error - could not calculate dominant colour --> {error}", force=True)
                    return ("ff000000", "0")
                else:
                    # Convert to RGB and calculate luminosity
                    dominant = palette[palette_index * 3:palette_index * 3 + 3]
                    luminosity = self.return_luminosity(dominant)
                    luminosity = int(luminosity * 1000)
                    dominant = self._rgb_to_hex(dominant)
                    return (dominant, str(luminosity))
            finally:
                paletted.close()

    def _rgb_to_hex(self, rgb):
        red, green, blue = rgb[:3]
        hex_color = "ff%02x%02x%02x" % (red, green, blue)
        return hex_color


class SlideshowMonitor:
    MAX_FETCH_COUNT = 20

    def __init__(self, sqlite_handler=None):
        self.sqlite = sqlite_handler if sqlite_handler else SQLiteHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor
        self.slideshow_path = self._get_slideshow_path()
        self.slideshow_source = self._check_slideshow_source()
        self.fetch_count = 0
        self.art = []

    def background_slideshow(self):
        # Fetch art types
        self.art_type = infolabel("Skin.String(slideshow_type)") or "global"
        content_map = {
            "movies": "movies",
            "tvshows": "tvshows",
            "music": "artists"
        }
        if self.art_type == "global":
            self.art_types = [
                content_map[k] for k in content_map if condition(f"Library.HasContent({k})")
            ]
        elif self.art_type == "videos":
            self.art_types = [
                content_map[k] for k in ["movies", "tvshows"] if condition(f"Library.HasContent({k})")
            ]
        elif self.art_type == "custom":
            self.art_types = ["custom"]
        else:
            self.art_types = [content_map.get(self.art_type, self.art_type)] if condition(
                f"Library.HasContent({self.art_type})") else []
        # Get art every 20 calls
        if (
            self.fetch_count == 0
            or not self.art
            or (new_path := self._get_slideshow_path()) != self.slideshow_path
            or (new_source := self._check_slideshow_source()) != self.slideshow_source
        ):
            self.slideshow_path, self.slideshow_source = new_path, new_source
            log("SlideshowMonitor: Fetching background art")
            self._get_art()
        self.fetch_count = (self.fetch_count + 1) % self.MAX_FETCH_COUNT
        # Set art every call
        self._set_art()

    def _get_art(self):
        if not self.art_types:
            log("SlideshowMonitor: No slideshow artwork available, skipping fetch")
            return
        self.art = []
        if "custom" in self.art_type:
            if not self.slideshow_path:
                log("SlideshowMonitor: No custom slideshow path found, skipping fetch")
                return
            # Get plugin art
            if "library" not in self.slideshow_source and condition("Integer.IsGreater(Container(3300).NumItems,0)"):
                log("SlideshowMonitor: Fetching plugin-based artwork")
                self._get_plugin_art()
                return
            # Get custom library art
            log(
                f"SlideshowMonitor: Fetching custom library art from {self.slideshow_path}")
            query = json_call(
                "Files.GetDirectory",
                params={"directory": self.slideshow_path},
                sort={"method": "random"},
                limit=self.MAX_FETCH_COUNT, parent="get_directory"
            )
            for result in query.get("result", {}).get("files", []):
                item_type, item_id = result.get("type"), result.get("id")
                dbtype = "Video" if item_type != "artist" else "Audio"
                details_query = json_call(
                    f"{dbtype}Library.Get{item_type}Details",
                    params={"properties": ["art"], f"{item_type}id": item_id},
                    parent="get_item_details"
                )
                item_details = details_query.get(
                    "result", {}).get(f"{item_type}details", {})
                art_data = item_details.get("art", {})
                if art_data.get("fanart"):
                    self.art.append(
                        {"title": item_details.get("label", ""), **art_data})
        # Get predefined library art
        else:
            log("SlideshowMonitor: Fetching predefined library artwork")
            for art_type in self.art_types:
                dbtype = "Video" if art_type != "artists" else "Audio"
                query = json_call(f"{dbtype}Library.Get{art_type}", properties=["art"], sort={
                    "method": "random"}, limit=self.MAX_FETCH_COUNT, parent="get_art")
                for result in query.get("result", {}).get(art_type, []):
                    if result.get("art").get("fanart"):
                        self.art.append(
                            {"title": result.get("label", ""), **result["art"]})
        if len(self.art) > self.MAX_FETCH_COUNT:
            self.art = random.sample(self.art, self.MAX_FETCH_COUNT)
        log(f"SlideshowMonitor: Total artwork found: {len(self.art)}" if self.art else "SlideshowMonitor: WARNING - No artwork was found!", force=not self.art)

    def _get_plugin_art(self):
        self.art.extend(
            item for i in range(int(infolabel("Container(3300).NumItems")))
            if (fanart := infolabel(f"Container(3300).ListItem({i}).Art(fanart)")) or
            ("folder" in (self.slideshow_source or "") and
             (fanart := infolabel(f"Container(3300).ListItem({i}).Art(thumb)")))
            if (item := {
                "title": infolabel(f"Container(3300).ListItem({i}).Label"),
                "fanart": fanart,
                "clearlogo": infolabel(f"Container(3300).ListItem({i}).Art(clearlogo)")
            })
        )

    def _get_slideshow_path(self):
        current_time = time.localtime().tm_hour
        start = int(infolabel("Skin.String(slideshow_start)") or 6)
        alt_start = int(infolabel("Skin.String(alt_slideshow_start)") or 20)
        is_alt_slideshow = (
            (alt_start > start and (current_time >= alt_start or current_time < start)) or
            (alt_start <= start and start > current_time >= alt_start)
        )
        slideshow = "alt_" if is_alt_slideshow else ""
        return infolabel(f"Skin.String({slideshow}slideshow_path)")

    def _check_slideshow_source(self):
        if "plugin://" in self.slideshow_path:
            return "plugin"
        return "library" if any(x in self.slideshow_path for x in ["db://", "library://", ".xsp", ".xml"]) else "folder"

    def _set_art(self):
        # Ensure items exist before proceeding
        if not self.art:
            log("SlideshowMonitor: No artwork available, waiting for next fetch", force=True)
            return
        # Select a random artwork and remove it from the list
        art = self.art.pop(random.randrange(len(self.art)))
        # Extract the first fanart
        fanart = next((art[k] for k in art if "fanart" in k), None)
        if fanart:
            fanart = url_decode_path(fanart)
            fanart = fanart[:-21] if "transform?size=thumb" in fanart else fanart
        # Extract and process clearlogo
        if clearlogo := art.get("clearlogo-billboard") or art.get("clearlogo"):
            clearlogo = url_decode_path(clearlogo)
            clearlogo_type = "clearlogo-billboard" if "billboard" in clearlogo else "clearlogo"
            processed = self.image_processor(
                url=clearlogo, processes={clearlogo_type: "crop"})
            clearlogo_path = processed.get(clearlogo_type)
        else:
            clearlogo_path = None
        # Set window properties
        window_property("slideshow_fanart", set=fanart)
        window_property("slideshow_clearlogo", set=clearlogo_path)
        window_property("slideshow_title", set=art.get("title"))
