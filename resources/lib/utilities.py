#!/usr/bin/python
# coding: utf-8

import hashlib
import json
import os
import sys
import urllib.parse as urllib

import xbmc
import xbmcvfs
from xbmcaddon import Addon
from xbmcgui import Dialog, Window
from xbmcplugin import setContent, setPluginCategory

ADDON = Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDONDATA = 'special://profile/addon_data/script.copacetic.helper/'
CROPPED_FOLDERPATH = os.path.join(ADDONDATA, 'crop/')

DEBUG = xbmc.LOGDEBUG
INFO = xbmc.LOGINFO
WARNING = xbmc.LOGWARNING
ERROR = xbmc.LOGERROR

DIALOG = Dialog()
VIDEOPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
MUSICPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)


def clear_playlists():
    log('Clear playlists')
    VIDEOPLAYLIST.clear()
    MUSICPLAYLIST.clear()
    MUSICPLAYLIST.unshuffle()


def condition(condition):
    return xbmc.getCondVisibility(condition)


def crop_image(source):
    from PIL import Image

    # Create cropped url
    source = urllib.unquote(source.replace('image://', ''))
    if source.endswith('/'):
        source = source[:-1]
    thumb = xbmc.getCacheThumbName(source).replace('.tbn', '')
    cropped_filename = f'{hashlib.md5(thumb.encode()).hexdigest()}.png'
    directory = xbmcvfs.validatePath(xbmcvfs.translatePath(CROPPED_FOLDERPATH))
    cropped_url = os.path.join(directory, cropped_filename)

    # Check if crop folder exists, otherwise create it
    if not xbmcvfs.exists(directory):
        try:  # Try makedir to avoid race conditions
            xbmcvfs.mkdirs(directory)
        except FileExistsError:
            pass

    # Check if cropped image exists for listitem, otherwise create it
    if not xbmcvfs.exists(cropped_url):
        json_response = json_call(
            'Textures.GetTextures',
            properties=["cachedurl"],
            query_filter={"field": "cachedurl",
                          "operator": "contains", "value": thumb},
            parent='crop_image'
        )
        try:
            filename = json_response['result']['textures'][0].get('cachedurl')
        except IndexError:
            return
        else:
            cached_url = os.path.join(
                'special://profile/Thumbnails/', filename)
            image = Image.open(xbmcvfs.translatePath(cached_url))
            image = image.crop(image.convert('RGBa').getbbox())
            with xbmcvfs.File(cropped_url, 'wb') as f:
                image.save(f, 'PNG')
                log(f'Image cropped and saved: {source} --> {cropped_url}')
            image.close()
    # Open new image and resize to get scaled height value
    image = Image.open(xbmcvfs.translatePath(cropped_url))
    image.thumbnail((600,240))
    cropped_size = image.size
    image.close

    return cropped_url, cropped_size


def get_cropped_clearlogo(key='ListItem', **kwargs):
    if key == 'ListItem' or key == 'VideoPlayer':
        path = key
    else:
        path = f'Container({key}).ListItem'
    clearlogos = [
        'clearlogo',
        'clearlogo-alt',
        'clearlogo-billboard'
    ]
    for item in clearlogos:
        source = xbmc.getInfoLabel(f'{path}.Art({item})')
        cropped_image = crop_image(source) if source else None
        if cropped_image:
            #set url to cropped clearlogo and its size after being rescaled
            window_property(f'{item}_cropped', set_property=cropped_image[0])
            window_property(f'{item}_cropped-height', set_property=cropped_image[1][1])
        else:
            window_property(f'{item}_cropped', clear_property=True)
            window_property(f'{item}_cropped-height', clear_property=True)


def get_joined_items(item):
    if len(item) > 0 and item is not None:
        item = ' / '.join(item)
    else:
        item = ''
    return item


def infolabel(infolabel):
    return xbmc.getInfoLabel(infolabel)


def json_call(method, properties=None, sort=None, query_filter=None, limit=None, params=None, item=None, options=None, limits=None, parent=None, debug=False):
    json_string = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {}}

    if properties is not None:
        json_string['params']['properties'] = properties
    if limit is not None:
        json_string['params']['limits'] = {'start': 0, 'end': int(limit)}
    if sort is not None:
        json_string['params']['sort'] = sort
    if query_filter is not None:
        json_string['params']['filter'] = query_filter
    if options is not None:
        json_string['params']['options'] = options
    if limits is not None:
        json_string['params']['limits'] = limits
    if item is not None:
        json_string['params']['item'] = item
    if params is not None:
        json_string['params'].update(params)

    jsonrpc_call = json.dumps(json_string)
    result = xbmc.executeJSONRPC(jsonrpc_call)
    result = json.loads(result)

    if (ADDON.getSettingBool('json_logging') or debug):
        log(f'JSON call for function {parent} ' +
            json_print(json_string), force=debug)
        log(f'JSON result for function {parent} ' +
            json_print(result), force=debug)
    return result


def json_print(string):
    return json.dumps(string, sort_keys=True, indent=4, separators=(',', ': '))


def log(message, loglevel=DEBUG, force=False):
    if (ADDON.getSettingBool('debug_logging') or force) and loglevel not in [WARNING, ERROR]:
        loglevel = INFO
    xbmc.log(f'{ADDON_ID} --> {message}', loglevel)


def log_and_execute(action):
    log(f'Execute: {action}', DEBUG)
    xbmc.executebuiltin(action)


def set_plugincontent(content=None, category=None):
    if category:
        setPluginCategory(int(sys.argv[1]), category)
    if content:
        setContent(int(sys.argv[1]), content)


def window_property(key, set_property=False, clear_property=False, window_id=10000, debug=False):
    window = Window(window_id)
    if clear_property:
        window.clearProperty(key)
        log(f'Window property: Clear, {window_id}, {key}', force=debug)
    if set_property:
        window.setProperty(key, f'{set_property}')
        log(f'Window property: Set, {window_id}, {key}, {set_property}', force=debug)
