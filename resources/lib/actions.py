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


def play_music(id, **kwargs):
    clear_playlists()

    method = kwargs.get('method', '')
    shuffled = True if method == 'shuffle' else False

    if method == 'from_here':
        method = f'Container({id}).ListItemNoWrap'
    else:
        method = f'Container({id}).ListItemAbsolute'

    for count in range(int(xbmc.getInfoLabel(f'Container({id}).NumItems'))):

        dbid = int(xbmc.getInfoLabel(f'{method}({count}).DBID'))
        url = xbmc.getInfoLabel(f'{method}({count}).Filenameandpath')

        if dbid:
            json_call('Playlist.Add', item={
                      'songid':dbid}, params={'playlistid':0})
        elif url:
            json_call('Playlist.Add', item={
                      'file':url}, params={'playlistid':0})

    json_call('Player.Open', item={'playlistid':0, 'position':0}, options={
              'shuffled':shuffled})


def play_album(**kwargs):
    clear_playlists()
    
    dbid = int(kwargs.get('id', False))
    json_call('Player.Open', item={f'albumid':dbid})


def play_album_from_song(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    track = int(kwargs.get('track', False)) - 1

    json_response = json_call('AudioLibrary.GetSongDetails', params={'properties':['albumid'], 'songid':dbid})    

    if json_response['result'].get('songdetails', None):
        albumid = json_response['result']['songdetails']['albumid']

    json_call('Player.Open', item={f'albumid':albumid})
    if track > 0:
        json_call('Player.GoTo', params={'playerid':0, 'to':track})


'''
log(f'FUCK --> {track} --> {json_response}',force=True)
FUCK --> 3 --> {'id': 1, 'jsonrpc': '2.0', 'result': {'songdetails': {'albumid': 20, 'label': 'A Million Random Digits', 'songid': 248}}}
'''
        


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
