# author: realcopacetic

import hashlib
import random

from PIL import Image

from resources.lib.service.xml import XMLHandler
from resources.lib.utilities import (BLUR_FOLDERPATH, CROP_FOLDERPATH, TEMP_FOLDERPATH,
                                     condition, infolabel, json_call,
                                     log, os, url_decode_path, validate_path,
                                     window_property, xbmc, xbmcvfs)


class ImageEditor:
    def __init__(self, xml_handler=None):
        self.xml = xml_handler if xml_handler else XMLHandler()
        self.clearlogo_bbox = (600, 240)
        self.blur_folder = BLUR_FOLDERPATH
        self.crop_folder = CROP_FOLDERPATH
        self.temp_folder = TEMP_FOLDERPATH

    def image_handler(self, url=False, art_type='clearlogo', source='ListItem', process="crop"):
        # fetch art url
        path = source if source in [
            'ListItem', 'VideoPlayer'
        ] else f'Container({source}).ListItem'
        art = {art_type: url} if url else self._fetch_art_url(
            art_type, path)
        # find art in lookup table or process and write to lookup if missing
        attributes = self._lookup_art(art)
        if not attributes:
            process_method = getattr(self, f'_{process}_art', None)
            attributes = process_method(art, path)
            self._write_lookup(art_type, attributes)
        return attributes
    
        """
                    
                    clearlogos_root = root.find('clearlogos')
                    self.xml.add_sub_element(
                        clearlogos_root, 'clearlogo', attributes)
            # Write to disk and populate window props for use within skin.copacetic
            self.xml.write()


        root = self.xml.get_root()
        for key, value in list(clearlogos.items()):
            name = type or key
            destination, height, color, luminosity = 0, 0, 'ff000000', 0
            if value:
                for node in root.find('clearlogos'):
                    clearlogo_path = node.attrib.get('path', None)
                    if value in node.attrib['name'] and validate_path(clearlogo_path):
                        destination = clearlogo_path
                        height = node.attrib.get('height', None)
                        color = node.attrib.get('color', None)
                        luminosity = node.attrib.get('luminosity', None)
                        break
                else:
                    destination, height, color, luminosity = self._crop_image(
                        value)
                    attributes = {
                        'name': value,
                        'path': destination,
                        'height': str(height),
                        'color': color,
                        'luminosity': str(luminosity)
                    }
                    clearlogos_root = root.find('clearlogos')
                    self.xml.add_sub_element(
                        clearlogos_root, 'clearlogo', attributes)
            # Write to disk and populate window props for use within skin.copacetic
            self.xml.write()
            reporting_key = reporting_key + '_' if reporting_key else ''
            reporting(key=f'{reporting_key}{name}_cropped', set=destination)
            reporting(key=f'{reporting_key}{name}_cropped-height', set=height)
            if return_color:
                reporting(
                    key=f'{reporting_key}{name}_cropped-color', set=color)
                reporting(
                    key=f'{reporting_key}{name}_cropped-luminosity', set=luminosity)
            return destination
            """

    def _fetch_art_url(self, art_type, path):
        art = {art_type: False}
        url = infolabel(f'{path}.Art({art_type})')
        if url:
            art[art_type] = url
        return art

    def _lookup_art(self, art):
        root = self.xml.get_root()
        art = list(art.items())[0]
        for node in root.find(f'{art[0]}s'):
            processed = node.attrib.get('processed', None)
            if art[1] in node.attrib['url'] and validate_path(processed):
                attributes = {key: value for key, value in node.attrib.items()}
                return attributes
    
    def _write_lookup(self, art_type, attributes):
        root = self.xml.get_root()
        art_type_root = root.find(f'{art_type}s')
        self.xml.add_sub_element(art_type_root, art_type, attributes)
        self.xml.write()

    def _blur_art(self, art):
        art = list(art.items())[0]
        filepath = self._get_filepath(art[1], self.blur_folder, '.jpg')
        url = self._get_cached_art(filepath, '.jpg')

    def _crop_art(self, art, path):
        art = list(art.items())[0]
        filepath = self._get_filepath(art[1], self.crop_folder, '.png')
        url = self._get_cached_art(filepath, '.png')
        #  Open and crop, then get height and color
        try:
            image = self._image_open(url)
        except Exception as error:
            log(
                f'ImageEditor: Error - could not open cached image --> {error}', force=True)
        else:
            converted_image = Image.new("RGBA", image.size)
            converted_image.paste(image)
            image = converted_image
            try:
                image = image.crop(image.convert('RGBa').getbbox())
            except ValueError as error:
                log(
                    f'ImageEditor: Error - could not convert image due to unsupport mode {image.mode} --> {error}', force=True)
            else:
                # Resize image to max 1600 x 620, 2x standard kodi size of 800x310
                width, height = image.size
                if width > 1600 or height > 620:
                    image.thumbnail((1600, 620))
                with xbmcvfs.File(filepath, 'wb') as f:  # Save new image
                    image.save(f, 'PNG')
                height, color, luminosity = self._image_functions(image)
                log(
                    f'ImageEditor: Image cropped and saved: {url} --> {filepath}')
                if self.temp_folder in url:  # If temp file  created, delete it now
                    xbmcvfs.delete(url)
                    log(f'ImageEditor: Temporary file deleted --> {url}')
        return {
            'id': infolabel(f'{path}.dbid'),
            'url': art[1],
            'processed': filepath, 
            'height': height, 
            'color': color, 
            'luminosity': luminosity
        }

    def _get_filepath(self, url, folder, suffix):
        filename = f'{hashlib.md5(url.encode()).hexdigest()}.png'
        filepath = url_decode_path(os.path.join(folder, filename))
        return filepath

    def _get_cached_art(self, filepath, suffix):
        cached_thumb = xbmc.getCacheThumbName(filepath).replace('.tbn', '')
        cached_url = os.path.join(
            'special://profile/Thumbnails/', f'{cached_thumb[0]}/', cached_thumb + suffix)
        if validate_path(cached_url):
            return cached_url
        return self._create_temp_file(filepath, suffix)

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
        image.close()
        return str(height), color, luminosity

    def _return_dominant_color(self, image):
        width, height = 25, 10
        small_image = image.copy()
        small_image.thumbnail((width, height))
        # Remove transparent pixels
        pixeldata = small_image.getcolors(width * height)
        sorted_pixeldata = sorted(pixeldata, key=lambda t: t[0], reverse=True)
        opaque_pixeldata = [p for p in sorted_pixeldata if p[-1][-1] > 64]
        opaque_pixels = [color for count,
                         color in opaque_pixeldata for _ in range(count)]
        if not opaque_pixeldata:
            log('ImageEditor: Error - No opaque pixels found for calculation of dominant colour and luminosity', force=True)
            return ('ff000000', 0)
        else:
            # Create a palette directly from the opaque pixels
            paletted = Image.new('RGBA', (len(opaque_pixels), 1))
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
                    f'ImageEditor: Error - could not calculate dominant colour for {infolabel("ListItem.Label")} --> {error}', force=True)
                return ('ff000000', 0)
            else:
                # Convert to rgb and calculate luminosity
                dominant = palette[palette_index*3:palette_index*3+3]
                luminosity = self.return_luminosity(dominant)
                luminosity = int(luminosity * 1000)
                dominant = self._rgb_to_hex(dominant)
                return (dominant, str(luminosity))

    def _create_temp_file(self, cleaned_source, suffix):
        # Create temp file to avoid access issues to direct source
        filename = f'{hashlib.md5(cleaned_source.encode()).hexdigest()}.png'
        destination = os.path.join(self.temp_folder, filename)
        if not validate_path(destination):
            xbmcvfs.copy(cleaned_source, destination)
            log(f'ImageEditor: Temporary file created --> {destination}')
        return destination

    def _return_scaled_height(self, image):
        image.thumbnail(self.clearlogo_bbox)
        return image.size[1] if image.size else 0

    def _rgb_to_hex(self, rgb):
        red, green, blue = rgb[:3]
        hex_color = 'ff%02x%02x%02x' % (red, green, blue)
        return hex_color


class SlideshowMonitor:
    MAX_FETCH_COUNT = 20

    def __init__(self, xml_handler=None):
        self.xml = xml_handler if xml_handler else XMLHandler()
        self.cropper = ImageEditor(self.xml).image_handler
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
