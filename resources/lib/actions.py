#!/usr/bin/python
# coding: utf-8


import xbmc
from resources.lib.helper import *


def dialog_yesno(heading, message, **kwargs):
    yes_actions = kwargs.get('yes_actions', '').split('|')
    no_actions = kwargs.get('no_actions', 'Null').split('|')

    if DIALOG.yesno(heading, message):
        for action in yes_actions:
            log_and_execute(action)
    else:
        for action in no_actions:
            log_and_execute(action)


def play_items(id, **kwargs):
    clear_playlists()

    method = kwargs.get('method', '')
    shuffled = True if method == 'shuffle' else False
    playlistid = 0 if kwargs.get('type', '') == 'music' else 1

    if method == 'from_here':
        method = f'Container({id}).ListItemNoWrap'
    else:
        method = f'Container({id}).ListItemAbsolute'

    for count in range(int(xbmc.getInfoLabel(f'Container({id}).NumItems'))):

        if xbmc.getCondVisibility(f'String.IsEqual({method}({count}).DBType,movie)'):
            media_type = 'movie'
        elif xbmc.getCondVisibility(f'String.IsEqual({method}({count}).DBType,episode)'):
            media_type = 'episode'
        elif xbmc.getCondVisibility(f'String.IsEqual({method}({count}).DBType,song)'):
            media_type = 'song'
        elif xbmc.getCondVisibility(f'String.IsEqual({method}({count}).DBType,musicvideo)'):
            media_type = 'musicvideo'

        dbid = xbmc.getInfoLabel(f'{method}({count}).DBID')
        url = xbmc.getInfoLabel(f'{method}({count}).Filenameandpath')

        if media_type and dbid:
            json_call('Playlist.Add',
                      item={f'{media_type}id': int(dbid)},
                      params={'playlistid': playlistid}
                      )
        elif url:
            json_call('Playlist.Add',
                      item={'file': url},
                      params={'playlistid': playlistid}
                      )

    json_call('Player.Open',
              item={'playlistid': playlistid, 'position': 0},
              options={'shuffled': shuffled}
              )
    
    json_call('Playlist.GetItems',
              params={'playlistid': playlistid}
              )


def shuffle_artist(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    json_call('Player.Open', item={
              'artistid': dbid}, options={'shuffled': True})


def play_album(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    json_call('Player.Open', item={
              'albumid': dbid}, options={'shuffled': False})


def play_album_from_track_x(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    track = int(kwargs.get('track', False)) - 1

    json_response = json_call('AudioLibrary.GetSongDetails', params={
                              'properties': ['albumid'], 'songid': dbid})

    if json_response['result'].get('songdetails', None):
        albumid = json_response['result']['songdetails']['albumid']

    json_call('Player.Open', item={
              'albumid': albumid}, options={'shuffled': False})
    if track > 0:
        json_call('Player.GoTo', params={'playerid': 0, 'to': track})


def split(string, **kwargs):
    separator = kwargs.get('separator', ' / ')
    name = kwargs.get('name', 'Split')

    for count, value in enumerate(string.split(separator)):
        window_property(f'{name}.{count}', set_property=value)


def split_random_return(string, **kwargs):
    import random

    separator = kwargs.get('separator', ' / ')
    name = kwargs.get('name', 'SplitRandomReturn')
    random = random.choice(string.split(separator))

    window_property(f'{name}', set_property=random.strip())
