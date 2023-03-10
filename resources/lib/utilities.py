#!/usr/bin/python
# coding: utf-8
import json
import os
import sys

import xbmc
import xbmcvfs
from xbmcaddon import Addon
from xbmcgui import Dialog, Window
from xbmcplugin import setContent, setPluginCategory

ADDON = Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDONDATA = 'special://profile/addon_data/script.copacetic.helper/'
CROPPED_FOLDERPATH = os.path.join(ADDONDATA, 'crop/')
CROPPED_FOLDERPATH = xbmcvfs.validatePath(
    xbmcvfs.translatePath(CROPPED_FOLDERPATH))
TEMP_FOLDERPATH = os.path.join(ADDONDATA, 'temp/')
TEMP_FOLDERPATH = xbmcvfs.validatePath(
    xbmcvfs.translatePath(TEMP_FOLDERPATH))

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


def get_folder_size(source=CROPPED_FOLDERPATH):
    bytes = 0
    if xbmcvfs.exists(source):
        dirs, files = xbmcvfs.listdir(source)
        for filename in files:
            path = os.path.join(source, filename)
            item = xbmcvfs.File(path)
            size = item.size()
            bytes += size
            item.close()
    return bytes


def get_cache_size(precision=1):
    temp_size, crop_size = 0, 0
    if xbmcvfs.exists(TEMP_FOLDERPATH):
        temp_size = get_folder_size(source=TEMP_FOLDERPATH)
    if xbmcvfs.exists(CROPPED_FOLDERPATH):
        crop_size = get_folder_size(source=CROPPED_FOLDERPATH)
    size = temp_size + crop_size
    ''' Credit Doug Latornell for bitshift method
    https://code.activestate.com/recipes/577081-humanized-representation-of-a-number-of-bytes/
    '''
    abbrevs = (
        (1 << 30, 'GB'),
        (1 << 20, 'MB'),
        (1 << 10, 'KB'),
        (1, 'bytes')
    )
    for factor, suffix in abbrevs:
        if size >= factor:
            break
    readable = '%.*f %s' % (precision, size / factor,
                            suffix) if size > 0 else '0.0 bytes'
    window_property('Addon_Data_Folder_Size', set=readable)
    return readable


def clear_cache(**kwargs):
    readable_size = get_cache_size()
    if xbmcvfs.exists(TEMP_FOLDERPATH):
        xbmcvfs.rmdir(TEMP_FOLDERPATH, force=True)
    if xbmcvfs.exists(CROPPED_FOLDERPATH):
        xbmcvfs.rmdir(CROPPED_FOLDERPATH, force=True)
        log(f'Clearlogo cache cleared by user. {readable_size} saved.')
        string = ADDON.getLocalizedString(
            32201) + f', {readable_size} ' + ADDON.getLocalizedString(32202) + '.'
        DIALOG.notification(ADDON_ID, string)
    get_cache_size()


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
            pretty_print(json_string), force=debug)
        log(f'JSON result for function {parent} ' +
            pretty_print(result), force=debug)
    return result


def pretty_print(string):
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


def skin_string(key, set=False, clear=False):
    clear = True if not set else False
    if clear:
        xbmc.executebuiltin(f"Skin.SetString({key},)")
    if set:
        xbmc.executebuiltin(f'Skin.SetString({key}, {set})')


def window_property(key, set=False, clear=False, window_id=10000, debug=False):
    clear = True if not set else False
    window = Window(window_id)
    if clear:
        window.clearProperty(key)
        log(f'Window property: Clear, {window_id}, {key}', force=debug)
    if set:
        window.setProperty(key, f'{set}')
        log(f'Window property: Set, {window_id}, {key}, {set}', force=debug)
