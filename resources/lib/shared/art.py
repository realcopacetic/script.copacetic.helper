# author: realcopacetic

import random
import time

from PIL import Image, ImageFilter

from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.utilities import (BLUR_FOLDERPATH, CROP_FOLDERPATH,
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

    def image_processor(self, dbid, source, processes):
        log(
            f"ImageEditor: Processing image for dbid: {dbid}, source: {source}, processes: {processes}")
        attributes = []
        art = {}
        try:
            for art_type, process in processes.items():
                current_attributes = self._handle_image(
                    dbid=dbid, source=source, art_type=art_type, process=process)
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
                    for key in ["height", "color", "luminosity"]:
                        value = attribute.get(key)
                        if value is not None:
                            art[f'{attribute["category"]}_{key}'] = value
                except (TypeError, KeyError):
                    continue  # Skip empty attributes
            return art

    def _handle_image(self, dbid=False, source='Container.ListItem', url=False, art_type='clearlogo', process='crop'):
        # fetch art url
        art = {art_type: url} if url else self._fetch_art_url(
            source, art_type)
        if art:
            # check for processed art in lookup table
            attributes = self._read_lookup(art)
            # or process and write to lookup if missing
            if not attributes:
                process_method = getattr(self, f'_{process}_art', None)
                attributes = process_method(art)
                self._write_lookup(art_type, attributes)
            return attributes

    def _fetch_art_url(self, source, art_type):
        art = {art_type: False}
        if self._wait_for_art(source, art_type):
            art[art_type] = infolabel(f'{source}.Art({art_type})')
            return art

    def _wait_for_art(self, source, art_type):
        timeout = time.time() + 3  # Set a timeout 2s in the future
        while time.time() < timeout:
            if condition('!String.IsEmpty(Control.GetLabel(6010))'):
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
            art_type = 'clearlogo' if 'clearlogo' in art_type else art_type
            self.sqlite.add_entry(art_type, attributes)

    def _blur_art(self, art):
        def blur(image):
            start_time = time.perf_counter()  # Start timing
            image.thumbnail(self.blur_bbox, Image.LANCZOS)
            image = image.filter(ImageFilter.GaussianBlur(radius=50))
            end_time = time.perf_counter()  # Stop timing
            log(f'ImageEditor: Blur time: {end_time - start_time:.6f} seconds')
            return {
                'image': image,
                'format': 'JPEG'
            }
        return self._process_image(self.blur_folder, art, '.jpg', blur)

    def _crop_art(self, art):
        def crop(image):
            start_time = time.perf_counter()  # Start timing
            log(f'FUCK {image.mode}', force=True)
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
                    f'ImageEditor: Error - could not convert image due to unsupported mode {image.mode} --> {error}', force=True)
                return None
            # Resize image to max 1600 x 620, 2x standard kodi size of 800x310
            width, height = image.size
            if width > 1600 or height > 620:
                image.thumbnail((1600, 620), Image.LANCZOS)
            height, color, luminosity = self._image_functions(image)
            end_time = time.perf_counter()  # Stop timing
            log(f'ImageEditor: Crop time: {end_time - start_time:.6f} seconds')
            return {
                'image': image,
                'format': 'PNG',
                'metadata': {'height': height, 'color': color, 'luminosity': luminosity}
            }
        return self._process_image(self.crop_folder, art, '.png', crop)

    def _process_image(self, folder, art, extension, process_func):
        art = list(art.items())[0]
        url = art[1]
        source_url, destination_url = self._generate_image_urls(
            folder, url, extension)
        try:
            image = self._image_open(source_url)
        except Exception as error:
            log(
                f'ImageEditor: Error - could not open cached image --> {error}', force=True)
            return None
        else:
            result = process_func(image)
            with xbmcvfs.File(destination_url, 'wb') as f:
                result['image'].save(f, result.get('format', 'PNG'))
                log(
                    f'ImageEditor: Image processed and saved: {url} --> {destination_url}')
                if self.temp_folder in source_url:  # If temp file created, delete it now
                    xbmcvfs.delete(source_url)
                    log(
                        f'ImageEditor: Temporary file deleted --> {source_url}')
            return {
                'category': art[0],
                'url': url,
                'processed': destination_url,
                # Merge additional metadata if available
                **result.get('metadata', {})
            }

    def _get_cached_thumb(self, url, suffix):
        # use source url to generate cached url
        cached_thumb = xbmc.getCacheThumbName(url).replace('.tbn', f'{suffix}')
        return cached_thumb

    def _generate_image_urls(self, folder, url, suffix):
        decoded_url = url_decode_path(url)
        cached_thumb = self._get_cached_thumb(decoded_url, suffix)
        source_url = os.path.join(
            f'special://profile/Thumbnails/{cached_thumb[0]}/', cached_thumb
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
            log(f'ImageEditor: Temporary file created --> {temp_url}')
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
        height = self._return_scaled_height(image)
        color, luminosity = self._return_dominant_color(image)
        return str(height), color, luminosity

    def _return_dominant_color(self, image):
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
            log('ImageEditor: Error - No opaque pixels found for calculation of dominant colour and luminosity', force=True)
            return ('ff000000', '0')
        else:
            # Create a palette directly from the opaque pixels
            paletted = Image.new('RGBA', (len(opaque_pixels), 1))
            try:
                paletted.putdata(opaque_pixels)
                paletted = paletted.convert(
                    'P', palette=Image.ADAPTIVE, colors=16)
                # Find color that occurs most often
                palette = paletted.getpalette()
                color_counts = sorted(paletted.getcolors(), reverse=True)
                try:
                    palette_index = color_counts[0][1]
                except IndexError as error:
                    log(
                        f'ImageEditor: Error - could not calculate dominant colour --> {error}', force=True)
                    return ('ff000000', '0')
                else:
                    # Convert to RGB and calculate luminosity
                    dominant = palette[palette_index * 3:palette_index * 3 + 3]
                    luminosity = self.return_luminosity(dominant)
                    luminosity = int(luminosity * 1000)
                    dominant = self._rgb_to_hex(dominant)
                    return (dominant, str(luminosity))
            finally:
                paletted.close()  # Now safe to close after it's fully used

    def _return_scaled_height(self, image):
        small_image = image.copy()  # Create a copy so the original image is not modified
        small_image.thumbnail(self.clearlogo_bbox)
        height = small_image.size[1] if small_image.size else 0
        small_image.close()  # Free up memory after calculation
        return height

    def _rgb_to_hex(self, rgb):
        red, green, blue = rgb[:3]
        hex_color = 'ff%02x%02x%02x' % (red, green, blue)
        return hex_color


class SlideshowMonitor:
    MAX_FETCH_COUNT = 20

    def __init__(self, sqlite_handler=None):
        self.sqlite = sqlite_handler if sqlite_handler else SQLiteHandler()
        self.cropper = ImageEditor(self.sqlite).image_processor
        # Establish available art types in the db:
        self.art_types = [art_type for art_type in ['movies', 'tvshows',
                                                    'video', 'music'] if condition(f'Library.HasContent({art_type})')]
        # Replace 'music' with 'artists' and extend the list
        self.art_types = ['artists' if art_type ==
                          'music' else art_type for art_type in self.art_types]
        self.art_types.extend(['custom', 'global'])
        # Initialize other variables
        self.fetch_count = self.MAX_FETCH_COUNT
        self.trigger_get_art = True
        self.custom_path = self._get_slideshow()
        self.custom_source = self._get_source()

    def background_slideshow(self):
        # Fetch art if it's required
        new_slideshow = self._get_slideshow()
        needs_update = (
            self.trigger_get_art or
            self.fetch_count >= self.MAX_FETCH_COUNT or
            self.custom_path != new_slideshow
        )
        if needs_update:
            # Reset trigger if it was cause
            if self.trigger_get_art:
                self.trigger_get_art = False
            # Update custom path and source if path changed
            if self.custom_path != new_slideshow:
                self.custom_path = new_slideshow
                self.custom_source = self._get_source()
            log('Monitor fetching background art')
            self._get_art()
            self.fetch_count = 1  # Reset fetch count
        else:
            self.fetch_count += 1  # Increment fetch count
        # Set art every interval
        for art_type in self.art_types:
            if art_type in self.art:  # Ensure key exists before accessing
                self._set_art(f'background_{art_type}', self.art[art_type])

    def _get_art(self):
        self.art = {type: [] for type in self.art_types}
        # Fetch custom art from external if conditions met
        if self.custom_path and 'library' not in self.custom_source and condition('Integer.IsGreater(Container(3300).NumItems,0)'):
            self._get_art_external()
        # Otherwise fetch custom art from library
        elif self.custom_path and 'library' in self.custom_source:
            query = json_call('Files.GetDirectory',
                              params={'directory': self.custom_path},
                              sort={'method': 'random'},
                              limit=self.MAX_FETCH_COUNT, parent='get_directory')
            try:
                for result in query['result']['files']:
                    type = result['type']
                    id = result['id']
                    dbtype = 'Video' if type != 'artist' else 'Audio'
                    query = json_call(f'{dbtype}Library.Get{type}Details',
                                      params={'properties': [
                                          'art'], f'{type}id': id},
                                      parent='get_item_details')
                    result = query['result'][f'{type}details']
                    if result['art'].get('fanart'):
                        data = {'title': result.get('label', '')}
                        data.update(result['art'])
                        self.art['custom'].append(data)
            except KeyError:
                pass
        # Populate video and music slidshows from library
        for item in ['movies', 'tvshows', 'artists']:
            if item in self.art_types:
                dbtype = 'Video' if item != 'artists' else 'Audio'
                query = json_call(f'{dbtype}Library.Get{item}', properties=['art'], sort={
                    'method': 'random'}, limit=self.MAX_FETCH_COUNT, parent='get_art')
                try:
                    for result in query['result'][item]:
                        if result['art'].get('fanart'):
                            data = {'title': result.get('label', '')}
                            data.update(result['art'])
                            self.art[item].append(data)
                except KeyError:
                    pass
        # Combine lists from self.art using generators to avoid key error for missing lists
        video_keys = ['movies', 'tvshows']
        global_keys = ['movies', 'tvshows', 'artists', 'custom']
        self.art['video'] = sum((self.art.get(key, [])
                                for key in video_keys), [])
        self.art['global'] = sum((self.art.get(key, [])
                                 for key in global_keys), [])
        # Trim both lists to self.MAX_FETCH_COUNT if they have more items
        for value in ['video', 'global']:
            if len(self.art[value]) > self.MAX_FETCH_COUNT:
                self.art[value] = random.sample(
                    self.art[value], self.MAX_FETCH_COUNT)
        return self.art

    def _get_art_external(self):
        num_items = int(infolabel('Container(3300).NumItems'))
        for i in range(num_items):
            fanart = infolabel(
                f'Container(3300).ListItem({i}).Art(fanart)')
            if not fanart and 'other' in self.custom_source:
                fanart = infolabel(
                    f'Container(3300).ListItem({i}).Art(thumb)')
            if fanart:
                item = {
                    'title': infolabel(
                        f'Container(3300).ListItem({i}).Label'),
                    'fanart': fanart,
                    'clearlogo': infolabel(
                        f'Container(3300).ListItem({i}).Art(clearlogo)')
                }
                self.art['custom'].append(item)

    def _slideshow_time(self, label, default):
        try:
            return int(infolabel(label))
        except ValueError:
            return default

    def _get_slideshow(self):
        slideshow = ''
        if condition('Skin.HasSetting(Background_Slideshow2)'):
            time = int(infolabel('System.Time(hh)'))
            am_pm = infolabel('System.Time(xx)')
            # Convert 12-hour format to 24-hour format
            if 'PM' in am_pm and time != 12:
                time += 12
            elif 'AM' in am_pm and time == 12:
                time = 0
            # Get the slideshow times, use default values in case of error
            slideshow_time = self._slideshow_time(
                'Skin.String(Background_Slideshow_Timer)', 6)
            slideshow2_time = self._slideshow_time(
                'Skin.String(Background_Slideshow2_Timer)', 20)
            # slideshow2 starts later in the day than slideshow...
            if slideshow2_time > slideshow_time:
                # ... so it is only active from slideshow2 start until end of day, or from 0 until slideshow start
                if time >= slideshow2_time or time < slideshow_time:
                    slideshow = '2'
            else:
                # slideshow2 doesn't start later, so it's only active from slideshow2 start until slideshow start
                if slideshow_time > time >= slideshow2_time:
                    slideshow = '2'
        window_property('CurrentSlideshow', set=slideshow)
        return infolabel(
            f'Skin.String(Background_Slideshow{slideshow}_Custom_Path)')

    def _get_source(self):
        library_strings = ['db://', 'library://', '.xsp', '.xml']
        if 'plugin://' in self.custom_path:
            source = 'plugin'
        elif any(x in self.custom_path for x in library_strings):
            source = 'library'
        else:
            source = 'other'
        return source

    def _set_art(self, key, items):
        if items:
            art = random.choice(items)
            # Remove the random selection from items after it's been stored
            items.remove(art)
            art.pop('set.fanart', None)
            fanarts = {k: v for k, v in art.items() if 'fanart' in k}
            if fanarts:
                fanart = url_decode_path(random.choice(list(fanarts.values())))
                if 'transform?size=thumb' in fanart:
                    fanart = fanart[:-21]
            window_property(f'{key}_fanart', set=fanart)
            clearlogo = art.get('clearlogo-billboard')
            type = 'clearlogo-billboard' if clearlogo else 'clearlogo'
            clearlogo = clearlogo or art.get('clearlogo')
            '''
            if clearlogo:
                clearlogo = url_decode_path(clearlogo)
                clearlogo = self.cropper(
                    url=clearlogo, art_type=type, reporting_key=key)
            '''
            window_property(f'{key}_title', set=art.get('title', False))
        else:
            self.trigger_get_art = True  # No items left, trigger refresh
