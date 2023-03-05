#!/usr/bin/python
# coding: utf-8
import random

from PIL import Image, ImagePalette

from resources.lib.utilities import *


class ImageEditor:
    def __init__(self):
        self.temp_folder = TEMP_FOLDERPATH
        self.cropped_folder = CROPPED_FOLDERPATH
        self.clearlogo_bbox = (600, 240)
        # Make crop directory if it doesn't exist
        if not self._validate_path(self.cropped_folder):
            self._create_dir(self.cropped_folder)

    def clearlogo_cropper(self, url=False, type='clearlogo', source='ListItem', return_height=False, return_color=False, reporting=window_property, reporting_key=None):
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
        crops = []
        for key, value in clearlogos.items():
            name = reporting_key or key
            if value:
                destination, height, color = self._crop_image(
                    value, key, return_height=return_height, return_color=return_color)
                reporting(key=f'{name}_cropped', set=destination)
                if return_height:
                    reporting(key=f'{name}_cropped-height', set=height)
                if return_color:
                    skin_string(key=f'{name}_cropped-color', set=color)
                crops.append((key, destination, height, color))
            else:
                reporting(key=f'{name}_cropped', clear=True)
                if return_height:
                    reporting(key=f'{name}_cropped-height', clear=True)
                if return_color:
                    skin_string(key=f'{name}_cropped-color', clear=True)
        return crops

    def _crop_image(self, url, key, return_height=True, return_color=True):
        # Generate destination filename for crop
        filename = f'{hashlib.md5(url.encode()).hexdigest()}.png'
        destination = os.path.join(self.cropped_folder, filename)
        # If file doesn't already exist, get image url, open and crop
        if not self._validate_path(destination):
            url = self._return_image_path(url)
            try:
                image = self._open_image(url)
            except Exception as error:
                log(f'ImageEditor: Error - could not open cached image --> {error}', force=True)
            else:
                if image.mode == 'LA':  # Manually convert if mode == 'LA'
                    converted_image = Image.new("RGBA", image.size)
                    converted_image.paste(image)
                    image.close()
                    image = converted_image
                image = image.crop(image.convert('RGBa').getbbox())
                with xbmcvfs.File(destination, 'wb') as f:
                    image.save(f, 'PNG')
                height, color = self._image_functions(
                    image, key, return_height=return_height, return_color=return_color)
                image.close()
                log(
                    f'ImageEditor: Image cropped and saved: {url} --> {destination}')
                if self.temp_folder in url:  # If temp file  created, delete it now
                    xbmcvfs.delete(url)
                    log(f'ImageEditor: Temporary file deleted --> {url}')
        else:
            image = self._open_image(destination)
            height, color = self._image_functions(image, key)
        return (destination, height, color)

    def _validate_path(self, path):
        return xbmcvfs.exists(path)

    def _create_dir(self, path):
        try:  # Try makedir to avoid race conditions
            xbmcvfs.mkdirs(path)
        except FileExistsError:
            return False

    def _return_image_path(self, source):
        # Use source URL to generate cached url. If cached url doesn't exist, return source url
        source = self._url_decode_path(source)
        cached_thumb = xbmc.getCacheThumbName(source).replace('.tbn', '')
        cached_url = os.path.join(
            'special://profile/Thumbnails/', f'{cached_thumb[0]}/', cached_thumb + '.png'
        )
        if self._validate_path(cached_url):
            return cached_url
        elif self._validate_path(source):
            # Create temp file to avoid access issues to direct source
            if not self._validate_path(self.temp_folder):
                self._create_dir(self.temp_folder)
            filename = f'{hashlib.md5(source.encode()).hexdigest()}.png'
            destination = os.path.join(self.temp_folder, filename)
            if not self._validate_path(destination):
                xbmcvfs.copy(source, destination)
                log(f'ImageEditor: Temporary file created --> {destination}')
                return destination

    def _url_decode_path(self, path):
        path = urllib.unquote(path.replace('image://', ''))
        path = path[:-1] if path.endswith('/') else path
        return path

    def _open_image(self, url):
        image = Image.open(xbmcvfs.translatePath(url))
        return image

    def _image_functions(self, image, key, return_height=True, return_color=True):
        height, color = False, False
        if return_height:
            height = self._return_scaled_height(image)
        if return_color:
            color = self._return_dominant_color(image, key)
        return (height, color)

    def _return_scaled_height(self, image):
        image.thumbnail(self.clearlogo_bbox)
        size = image.size
        height = size[1]
        return height

    def _return_dominant_color(self, image, key):
        width, height = 150, 60
        image.thumbnail((width, height))
        pixels = image.getcolors(width * height)
        sorted_pixels = sorted(pixels, key=lambda t: t[0], reverse=True)
        for position, pixel in enumerate(sorted_pixels):
            if pixel[-1][-1] >= 128:
                dominant = pixel[-1]
                break

        luminosity = self._return_luminosity(dominant)
        if (
            (
                key == 'clearlogo-alt' and luminosity < 0.66
            ) or
            (
                key == 'clearlogo' and luminosity > 0.066
            )
        ):

            dominant = self._rgb_to_hex(dominant)
            return dominant
        else:
            return False

    '''
        palette_size = 16
        solid_pixels = []
        # Resize image to speed up processing
        width, height = 150, 60
        image.thumbnail((width, height))

        # Reduce colors (uses k-means internally)
        paletted = image.convert(
            'P', palette=Image.ADAPTIVE, colors=palette_size)
        
        # Find the color that occurs most often
        palette = paletted.getpalette()
        color_counts = sorted(paletted.getcolors(), reverse=True)
        palette_index = color_counts[0][1]
        dominant = palette[palette_index*3:palette_index*3+3]
        dominant = self._rgb_to_hex(dominant)
        return dominant
        '''

    def _return_luminosity(self, rgba):
        # Credit to Mark Ransom for luminosity calculation
        # https://stackoverflow.com/questions/3942878/how-to-decide-font-color-in-white-or-black-depending-on-background-color
        rgb = rgba[:-1]
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

    def _rgb_to_hex(self, rgba):
        red, green, blue, alpha = rgba
        hex = 'ff%02x%02x%02x' % (red, green, blue)
        return hex


class SlideshowMonitor:
    def __init__(self):
        self.refresh_count = self.refresh_interval = self._get_refresh_interval()
        self.fetch_count = self.fetch_interval = self.refresh_interval * 30
        self.clearlogo_cropper = ImageEditor().clearlogo_cropper

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
        skin_string(f'{key}_Fanart', art.get('fanart', ''))
        skin_string(f'{key}_Clearlogo', art.get('clearlogo', ''))
        