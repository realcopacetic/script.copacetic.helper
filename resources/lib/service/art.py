#!/usr/bin/python
# coding: utf-8
import random

from resources.lib.utilities import (crop_image, infolabel, json_call, log,
                                     window_property)


class SlideshowMonitor:
    def __init__(self):
        self.refresh_count = self.refresh_interval = self._get_refresh_interval()
        self.fetch_count = self.fetch_interval = self.refresh_interval * 30

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
            query = json_call(
                f'{dbtype}Library.Get{item}',
                properties=['art'],
                sort={'method': 'random'},
                limit=40,
                parent='get_art'
            )
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
        window_property(f'{key}_Fanart', set_property=art.get('fanart', ''))
        clearlogo = art.get('clearlogo', '')
        if clearlogo:
            clearlogo_cropped = crop_image(clearlogo)
            if clearlogo_cropped:
                clearlogo = clearlogo_cropped
            window_property(f'{key}_Clearlogo', set_property=clearlogo)
        else:
            window_property(f'{key}_Clearlogo', clear_property=True)

    def background_slideshow(self):
        # Check if refresh interval has been adjusted in skin settings
        if self.refresh_interval != self._get_refresh_interval():
            self.refresh_count = self.refresh_interval = self._get_refresh_interval()
            self.fetch_count = self.fetch_interval = self.refresh_interval * 30

        # Fech art every 30 x refresh interval
        if self.fetch_count >= self.fetch_interval:
            log('Monitor fetching background art', force=True)
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
