# author: realcopacetic

import hashlib
import random
import urllib.parse as urllib
import xml.etree.ElementTree as ET

from PIL import Image

from resources.lib.utilities import (CROPPED_FOLDERPATH, LOOKUP_XML,
                                     TEMP_FOLDERPATH, condition, infolabel,
                                     json_call, log, os, url_decode_path,
                                     validate_path, window_property, xbmc,
                                     xbmcvfs)


class ImageEditor():
    def __init__(self):
        self.clearlogo_bbox = (600, 240)
        self.cropped_folder = CROPPED_FOLDERPATH
        self.temp_folder = TEMP_FOLDERPATH
        self.lookup = LOOKUP_XML
        self.destination, self.height, self.color, self.luminosity = False, False, False, False

    def clearlogo_cropper(self, url=False, type='clearlogo', source='ListItem', return_color=False, reporting=window_property, reporting_key=None):
        # establish clearlogo urls
        if url:
            clearlogos = {type: url}
        else:
            clearlogos = {
                'clearlogo': False,
                'clearlogo-alt': False,
                'clearlogo-billboard': False
            }
            if source == 'ListItem' or source == 'VideoPlayer':
                path = source
            else:
                path = f'Container({source}).ListItem'
            for key in clearlogos:
                url = infolabel(f'{path}.Art({key})')
                if url:
                    clearlogos[key] = url
        # lookup urls in table or run crop_image() and write values to table
        lookup_tree = ET.parse(self.lookup)
        root = lookup_tree.getroot()
        for key, value in list(clearlogos.items()):
            self.id = infolabel(f'{path}.dbid')
            self.destination, self.height, self.color, self.luminosity = False, False, False, False
            name = reporting_key or key
            if value:
                for node in root.find('clearlogos'):
                    if value in node.attrib['name'] and validate_path(node.find('path').text):
                        self.destination = node.find('path').text
                        self.height = node.find('height').text
                        self.color = node.find('color').text
                        self.luminosity = node.find('luminosity').text
                        break
                else:
                    self.crop_image(value)
                    clearlogo = ET.SubElement(
                        root.find('clearlogos'), 'clearlogo')
                    clearlogo.attrib['name'] = value
                    path = ET.SubElement(clearlogo, 'path')
                    path.text = self.destination
                    height = ET.SubElement(clearlogo, 'height')
                    height.text = str(self.height)
                    color = ET.SubElement(clearlogo, 'color')
                    color.text = self.color
                    luminosity = ET.SubElement(clearlogo, 'luminosity')
                    luminosity.text = str(self.luminosity)
                    lookup_tree.write(self.lookup, encoding="utf-8")
            reporting(key=f'{name}_cropped', set=self.destination)
            reporting(key=f'{name}_cropped-id', set=self.id)
            reporting(key=f'{name}_cropped-height', set=self.height)
            if return_color:
                reporting(key=f'{name}_cropped-color', set=self.color)
                reporting(key=f'{name}_cropped-luminosity',
                          set=self.luminosity)

    def crop_image(self, url):
        # Get image url
        filename = f'{hashlib.md5(url.encode()).hexdigest()}.png'
        self.destination = os.path.join(self.cropped_folder, filename)
        url = self._return_image_path(url, '.png')
        #  Open and crop, then get height and color
        try:
            image = self._open_image(url)
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
                with xbmcvfs.File(self.destination, 'wb') as f:  # Save new image
                    image.save(f, 'PNG')
                self._image_functions(image)
                log(
                    f'ImageEditor: Image cropped and saved: {url} --> {self.destination}')
                if self.temp_folder in url:  # If temp file  created, delete it now
                    xbmcvfs.delete(url)
                    log(f'ImageEditor: Temporary file deleted --> {url}')
        return (self.destination, self.height, self.color, self.luminosity)

    def return_luminosity(self, rgb):
        # Credit to Mark Ransom for luminosity calculation
        # https://stackoverflow.com/questions/3942878/how-to-decide-font-color-in-white-or-black-depending-on-background-color
        new_rgb = ()
        for channel in rgb:
            c = channel / 255.0
            if c <= 0.04045:
                output = c / 12.92
            else:
                output = pow(((c + 0.055) / 1.055), 2.4)
            new_rgb += (output,)
        r, g, b = new_rgb
        luminosity = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return luminosity

    def _image_functions(self, image):
        self.height = self._return_scaled_height(image)
        self.color, self.luminosity = self._return_dominant_color(image)
        image.close()

    def _open_image(self, url):
        image = Image.open(xbmcvfs.translatePath(url))
        return image

    def _return_average_color(self, image):
        h = image.histogram()
        # split into red, green, blue
        r = h[0:256]
        g = h[256:256*2]
        b = h[256*2: 256*3]
        # perform the weighted average of each channel:
        # the *index* is the channel value, and the *value* is its weight
        return (
            sum(i*w for i, w in enumerate(r)) / sum(r),
            sum(i*w for i, w in enumerate(g)) / sum(g),
            sum(i*w for i, w in enumerate(b)) / sum(b)
        )

    def _return_dominant_color(self, image):
        width, height = 75, 30
        image.thumbnail((width, height))
        # Remove transparent pixels
        pixeldata = image.getcolors(width * height)
        sorted_pixeldata = sorted(pixeldata, key=lambda t: t[0], reverse=True)
        opaque_pixeldata = [
            pixeldata for pixeldata in sorted_pixeldata if pixeldata[-1][-1] > 64]
        opaque_pixels = []
        for position, pixeldata in enumerate(opaque_pixeldata):
            for count in range(pixeldata[0]):
                opaque_pixels.append(pixeldata[1])
        # Reduce colors to palette
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
            return (False, False)
        else:
            # Convert to rgb and calculate luminosity
            dominant = palette[palette_index*3:palette_index*3+3]
            luminosity = self.return_luminosity(dominant)
            luminosity = int(luminosity * 1000)
            dominant = self._rgb_to_hex(dominant)
            return (dominant, luminosity)

    def _return_image_path(self, source, suffix):
        # Use source URL to generate cached url. If cached url doesn't exist, return source url
        cleaned_source = url_decode_path(source)
        cached_thumb = xbmc.getCacheThumbName(
            cleaned_source).replace('.tbn', '')
        cached_url = os.path.join(
            'special://profile/Thumbnails/', f'{cached_thumb[0]}/', cached_thumb + suffix)
        if validate_path(cached_url):
            return cached_url
        else:
            # Create temp file to avoid access issues to direct source
            filename = f'{hashlib.md5(cleaned_source.encode()).hexdigest()}.png'
            destination = os.path.join(self.temp_folder, filename)
            if not validate_path(destination):
                xbmcvfs.copy(cleaned_source, destination)
                log(f'ImageEditor: Temporary file created --> {destination}')
            return destination

    def _return_scaled_height(self, image):
        image.thumbnail(self.clearlogo_bbox)
        try:
            size = image.size
        except AttributeError:
            height = False
        else:
            height = size[1]
        return height

    def _rgb_to_hex(self, rgb):
        red, green, blue = rgb
        hex = 'ff%02x%02x%02x' % (red, green, blue)
        return hex


class SlideshowMonitor:
    MAX_FETCH_COUNT = 20
    DEFAULT_REFRESH_INTERVAL = 10

    def __init__(self):
        self.lookup = LOOKUP_XML
        self.art_types = ['global', 'movies',
                          'tvshows', 'video', 'music', 'custom']
        # Remove any art types not present in user library 
        for type in range(1,5):
            if not condition(f'Library.HasContent({self.art_types[type]})'):
                self.art_types.pop(type)
        # List comprehension to replace 'music' with 'artist' if it's present in the list
        self.art_types = ['artists' if 'music' in ele else ele for ele in self.art_types] 
        self.run_get_art_flag = True
        self.refresh_count = self.refresh_interval = self._get_refresh_interval()
        self.refreshing = False
        self.fetch_count = self.fetch_interval = self.refresh_interval * self.MAX_FETCH_COUNT
        self.custom_path = self._get_slideshow()
        self.custom_source = self._get_source()
        self._crop_image = ImageEditor().crop_image

    def background_slideshow(self):
        # Check if refresh interval has been adjusted in skin settings
        new_refresh_interval = self._get_refresh_interval()
        if self.refresh_interval != new_refresh_interval:
            self.refresh_interval = new_refresh_interval
            self.fetch_interval = self.refresh_interval * self.MAX_FETCH_COUNT

        # Fetch art if first run, if refresh interval reaches maximum count or if custom slideshow path has changed
        new_slideshow = self._get_slideshow()
        if (
            self.run_get_art_flag or self.fetch_count >= self.fetch_interval or self.custom_path != new_slideshow
        ) and not self.refreshing:
            log('Monitor fetching background art')
            self.run_get_art_flag = False
            self.custom_path = new_slideshow
            self.custom_source = self._get_source()
            self._get_art()
            self.fetch_count = 1  # Reset fetch count
        else:
            self.fetch_count += 1  # Increment fetch count

        # Set art every refresh interval
        if self.refresh_count >= self.refresh_interval:
            self.refreshing = True
            for art_type in self.art_types:
                if art_type in self.art:  # Ensure key exists before accessing
                    self._set_art(f'background_{art_type}', self.art[art_type])
            self.refreshing = False
            self.refresh_count = 1  # Reset refresh count
        else:
            self.refresh_count += 1  # Increment refresh count

    def _crop_clearlogo(self, url):
        lookup_tree = ET.parse(self.lookup)
        root = lookup_tree.getroot()
        for node in root.find('clearlogos'):
            if url in node.attrib['name'] and validate_path(node.find('path').text):
                path = node.find('path').text
                return path
        else:
            crop_destination, crop_height, crop_color, crop_luminosity = self._crop_image(
                url)
            clearlogo = ET.SubElement(
                root.find('clearlogos'), 'clearlogo')
            clearlogo.attrib['name'] = url
            path = ET.SubElement(clearlogo, 'path')
            path.text = crop_destination
            height = ET.SubElement(clearlogo, 'height')
            height.text = str(crop_height)
            color = ET.SubElement(clearlogo, 'color')
            color.text = crop_color
            luminosity = ET.SubElement(clearlogo, 'luminosity')
            luminosity.text = str(crop_luminosity)
            lookup_tree.write(self.lookup, encoding="utf-8")
            return crop_destination

    def fanart_read(self):
        lookup_tree = ET.parse(self.lookup)
        root = lookup_tree.getroot()
        for type in self.art_types:
            # try search on background tag, if it doesn't exist then create it at root level
            try:
                for node in root.find('backgrounds'):
                    if type in node.attrib['type'] and validate_path(node.find('path').text):
                        path = node.find('path').text
                        window_property(f'background_{type}_fanart', set=path)
            except TypeError:
                ET.SubElement(root, 'backgrounds')
                lookup_tree.write(self.lookup, encoding="utf-8")

    def fanart_write(self):
        lookup_tree = ET.parse(self.lookup)
        root = lookup_tree.getroot()
        for type in self.art_types:
            current_fanart = infolabel(
                f'Window(home).Property(background_{type}_fanart)')
            for node in root.find('backgrounds'):
                if type in node.attrib['type']:
                    background = node.find('path')
                    background.text = current_fanart
                    break
            else:
                background = ET.SubElement(
                    root.find('backgrounds'), 'background')
                background.attrib['type'] = type
                path = ET.SubElement(background, 'path')
                path.text = current_fanart
        lookup_tree.write(self.lookup, encoding="utf-8")

    def _get_art(self):
        # Clear art dictionary ahead of new fetch
        self.art = {}
        for type in self.art_types:
            self.art[type] = []
        # Fetch custom art from external if conditions met otherwise fetch from library
        if self.custom_path and 'library' not in self.custom_source and condition('Integer.IsGreater(Container(3300).NumItems,0)'):
            self._get_art_external()
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
        for type in self.art:
            if 'movies' in type or 'tvshows' in type:
                self.art['video'] += self.art[type]
                self.art['global'] += self.art[type]
            elif 'artists' in type or 'custom' in type:
                self.art['global'] += self.art[type]
        if len(self.art['video']) > 20:
            self.art['video'] = random.sample(self.art['video'],20)
        if len(self.art['global']) > 20:
            self.art['global'] = random.sample(self.art['global'], 20)
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

    def _get_refresh_interval(self):
        try:
            self.refresh_interval_check = int(
                infolabel('Skin.String(Background_Interval)')
            )
        except ValueError:
            self.refresh_interval_check = self.DEFAULT_REFRESH_INTERVAL
        return self.refresh_interval_check

    def _get_slideshow(self):
        if condition('Skin.HasSetting(Background_Slideshow2)'):
            time = int(infolabel('System.Time(hh)'))
            am_pm = infolabel('System.Time(xx)')
            # Convert 12-hour format to 24-hour format
            if 'PM' in am_pm and time != 12:
                time += 12
            elif 'AM' in am_pm and time == 12:
                time = 0
            # Get the slideshow times, use default values in case of error
            try:
                slideshow_time = int(
                    infolabel('Skin.String(Background_Slideshow_Timer)'))
            except ValueError:
                slideshow_time = 6
            try:
                slideshow2_time = int(
                    infolabel('Skin.String(Background_Slideshow2_Timer)'))
            except ValueError:
                slideshow2_time = 20
            # slideshow2 starts later in the day than slideshow...
            if slideshow2_time > slideshow_time:
                # ... so it is only active from slideshow2 start until end of day, or from 0 until slideshow start
                if time >= slideshow2_time or time < slideshow_time:
                    slideshow = '2'
                else:
                    slideshow = ''
            else:
                # slideshow2 doesn't start later, so it's only active from slideshow2 start until slideshow start
                if slideshow_time > time >= slideshow2_time:
                    slideshow = '2'
                else:
                    slideshow = ''
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
        if len(items) > 0:
            art = random.choice(items)
            items.remove(art)
            art.pop('set.fanart', None)
            fanarts = {key: value for (
                key, value) in art.items() if 'fanart' in key}
            fanart = random.choice(list(fanarts.values()))
            fanart = url_decode_path(fanart)
            if 'transform?size=thumb' in fanart:
                fanart = fanart[:-21]
            window_property(f'{key}_fanart', set=fanart)
            # clearlogo if present otherwise clear
            clearlogo = art.get('clearlogo-billboard', False)
            if not clearlogo:
                clearlogo = art.get('clearlogo', False)
            if clearlogo and condition('!Skin.HasSetting(Quick_Transitions)'):
                clearlogo = url_decode_path(clearlogo)
                clearlogo = self._crop_clearlogo(clearlogo)
            window_property(f'{key}_clearlogo', set=clearlogo)
            # title
            window_property(f'{key}_title', set=art.get('title', False))
        else:
            # if no items left, trigger get_art
            self.run_get_art_flag = True
