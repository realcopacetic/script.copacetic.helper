#!/usr/bin/python
# coding: utf-8

import hashlib
import random
import urllib.parse as urllib
import xml.etree.ElementTree as ET
import xml.dom.minidom

from PIL import Image

from resources.lib.utilities import (CROPPED_FOLDERPATH, TEMP_FOLDERPATH,
                                     condition, infolabel, json_call, log, os,
                                     skin_string, window_property, xbmc,
                                     xbmcvfs)

XMLSTR = '''<?xml version="1.0" encoding="utf-8"?>
<data>
    <clearlogos />
    <messages />
</data>
'''

class ImageEditor:
    def __init__(self):
        self.clearlogo_bbox = (600, 240)
        self.cropped_folder = CROPPED_FOLDERPATH
        self.temp_folder = TEMP_FOLDERPATH
        self.lookup = os.path.join(CROPPED_FOLDERPATH, '_lookup.xml')
        self._create_dirs()

    def _create_dirs(self):
        if not self._validate_path(self.cropped_folder):
            self._create_dir(self.cropped_folder)
        if not self._validate_path(self.temp_folder):
            self._create_dir(self.temp_folder)
        if not self._validate_path(self.lookup):
            root = ET.fromstring(XMLSTR)
            ET.ElementTree(root).write(self.lookup, xml_declaration=True, encoding="utf-8")

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
                url = xbmc.getInfoLabel(f'{path}.Art({key})')
                if url:
                    clearlogos[key] = url
        # lookup urls in table or run _crop_image() and write values to table
        lookup_tree = ET.parse(self.lookup)
        root = lookup_tree.getroot()
        for key, value in clearlogos.items():
            self.destination, self.height, self.color, self.luminosity = False, False, False, False
            name = reporting_key or key
            if value:
                for node in root[0]:
                    if value in node.attrib['name'] and self._validate_path(node.find('path').text):
                        self.destination = node.find('path').text
                        self.height = node.find('height').text
                        self.color = node.find('color').text
                        self.luminosity = node.find('luminosity').text
                        break
                else:
                    self._crop_image(value)
                    clearlogo = ET.SubElement(root[0], 'clearlogo')
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
            reporting(key=f'{name}_cropped-height', set=self.height)
            if return_color and condition('Skin.HasSetting(Colorise_Flags)'):
                skin_string(key=f'{name}_cropped-color', set=self.color)
                skin_string(key=f'{name}_cropped-luminosity',
                            set=self.luminosity)

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

    def _validate_path(self, path):
        return xbmcvfs.exists(path)

    def _create_dir(self, path):
        try:  # Try makedir to avoid race conditions
            xbmcvfs.mkdirs(path)
        except FileExistsError:
            return

    def _crop_image(self, url):
        filename = f'{hashlib.md5(url.encode()).hexdigest()}.png'
        self.destination = os.path.join(self.cropped_folder, filename)
        # If crop exists, open to get height and color
        if self._validate_path(self.destination):
            image = self._open_image(self.destination)
            self._image_functions(image)
        # else get image url, open and crop, then get height and color
        else:
            url = self._return_image_path(url, '.png')
            try:
                image = self._open_image(url)
            except Exception as error:
                log(
                    f'ImageEditor: Error - could not open cached image --> {error}', force=True)
            else:
                if image.mode == 'LA':  # Convert if mode == 'LA'
                    converted_image = Image.new("RGBA", image.size)
                    converted_image.paste(image)
                    image = converted_image
                image = image.crop(image.convert('RGBa').getbbox())
                with xbmcvfs.File(self.destination, 'wb') as f:
                    image.save(f, 'PNG')
                self._image_functions(image)
                log(
                    f'ImageEditor: Image cropped and saved: {url} --> {self.destination}')
                if self.temp_folder in url:  # If temp file  created, delete it now
                    xbmcvfs.delete(url)
                    log(f'ImageEditor: Temporary file deleted --> {url}')

    def _return_image_path(self, source, suffix):
        # Use source URL to generate cached url. If cached url doesn't exist, return source url
        cleaned_source = self.url_decode_path(source)
        cached_thumb = xbmc.getCacheThumbName(
            cleaned_source).replace('.tbn', '')
        cached_url = os.path.join(
            'special://profile/Thumbnails/', f'{cached_thumb[0]}/', cached_thumb + suffix)
        if self._validate_path(cached_url):
            return cached_url
        else:
            # Create temp file to avoid access issues to direct source
            filename = f'{hashlib.md5(cleaned_source.encode()).hexdigest()}.png'
            destination = os.path.join(self.temp_folder, filename)
            if not self._validate_path(destination):
                xbmcvfs.copy(cleaned_source, destination)
                log(f'ImageEditor: Temporary file created --> {destination}')
            return destination

    def url_decode_path(self, path):
        path = urllib.unquote(path.replace('image://', ''))
        path = path[:-1] if path.endswith('/') else path
        return path

    def _open_image(self, url):
        image = Image.open(xbmcvfs.translatePath(url))
        return image

    def _image_functions(self, image):
        self.height = self._return_scaled_height(image)
        self.color, self.luminosity = self._return_dominant_color(image)
        image.close()

    def _return_scaled_height(self, image):
        image.thumbnail(self.clearlogo_bbox)
        size = image.size
        height = size[1]
        return height

    def _return_dominant_color(self, image):
        width, height = 75, 30
        image.thumbnail((width, height))
        # Remove transparent pixels
        pixeldata = image.getcolors(width * height)
        sorted_pixeldata = sorted(pixeldata, key=lambda t: t[0], reverse=True)
        opaque_pixeldata = [
            pixeldata for pixeldata in sorted_pixeldata if pixeldata[-1][-1] > 128]
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
        palette_index = color_counts[0][1]
        # Convert to rgb and calculate luminosity
        dominant = palette[palette_index*3:palette_index*3+3]
        luminosity = self.return_luminosity(dominant)
        luminosity = int(luminosity * 1000)
        dominant = self._rgb_to_hex(dominant)
        return (dominant, luminosity)

    def _rgb_to_hex(self, rgb):
        red, green, blue = rgb
        hex = 'ff%02x%02x%02x' % (red, green, blue)
        return hex

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


class SlideshowMonitor:
    def __init__(self):
        self.refresh_count = self.refresh_interval = self._get_refresh_interval()
        self.fetch_count = self.fetch_interval = self.refresh_interval * 30
        self.decode_path = ImageEditor().url_decode_path

    def background_slideshow(self):
        # Check if refresh interval has been adjusted in skin settings
        if self.refresh_interval != self._get_refresh_interval():
            self.refresh_count = self.refresh_interval = self._get_refresh_interval()
            self.fetch_count = self.fetch_interval = self.refresh_interval * 30
        # Fech art every 30 x refresh interval
        if self.fetch_count >= self.fetch_interval:
            log('Monitor fetching background art')
            self.art = self._get_art()
            self.fetch_count = 0
        else:
            self.fetch_count += 1
        # Set art every refresh interval
        if self.refresh_count >= self.refresh_interval:
            if self.art.get('all'):
                self._set_art('Background_Global', self.art['all'])
            if self.art.get('movies'):
                self._set_art('Background_Movies', self.art['movies'])
            if self.art.get('tvshows'):
                self._set_art('Background_TVShows', self.art['tvshows'])
            if self.art.get('videos'):
                self._set_art('Background_Videos', self.art['videos'])
            if self.art.get('artists'):
                self._set_art('Background_Artists', self.art['artists'])
            self.refresh_count = 0
        else:
            self.refresh_count += 1

    def _get_refresh_interval(self):
        try:
            self.refresh_interval = int(
                infolabel('Skin.String(Background_Interval)')
            )
        except ValueError:
            self.refresh_interval = 10
        return self.refresh_interval

    def _get_art(self):
        self.art = {}
        self.art['movies'] = []
        self.art['tvshows'] = []
        self.art['artists'] = []
        self.art['musicvideos'] = []
        self.art['videos'] = []
        self.art['all'] = []
        for item in ['movies', 'tvshows', 'artists', 'musicvideos']:
            dbtype = 'Video' if item != 'artists' else 'Audio'
            query = json_call(f'{dbtype}Library.Get{item}', properties=['art'], sort={
                              'method': 'random'}, limit=40, parent='get_art')
            try:
                for result in query['result'][item]:
                    if result['art'].get('fanart'):
                        data = {'title': result.get('label', '')}
                        data.update(result['art'])
                        self.art[item].append(data)
            except KeyError:
                pass
        self.art['videos'] = self.art['movies'] + self.art['tvshows']
        for list in self.art:
            if self.art[list]:
                self.art['all'] = self.art['all'] + self.art[list]
        return self.art

    def _set_art(self, key, items):
        art = random.choice(items)
        #fanart = self.decode_path(art.get('fanart', ''))
        fanart = art.get('fanart', False)
        skin_string(key=f'{key}_Fanart', set=fanart)
        # clearlogo if present otherwise clear
        clearlogo = art.get('clearlogo', False)
        # if clearlogo:
        #clearlogo = self.decode_path(clearlogo)
        skin_string(key=f'{key}_Clearlogo', set=clearlogo)
