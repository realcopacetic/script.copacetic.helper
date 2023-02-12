#!/usr/bin/python
# coding: utf-8

import xbmc
import xbmcgui
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


def play_album(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    if dbid:
        json_call('Player.Open', 
                  item={'albumid': dbid}, 
                  options={'shuffled': False}
                  )


def play_album_from_track_x(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    track = int(kwargs.get('track', False)) - 1

    if dbid:
        json_response = json_call('AudioLibrary.GetSongDetails',
                                  params={'properties': ['albumid'],'songid': dbid}
                                  )

    if json_response['result'].get('songdetails', None):
        albumid = json_response['result']['songdetails']['albumid']

    json_call('Player.Open', item={
              'albumid': albumid}, options={'shuffled': False})
    if track > 0:
        json_call('Player.GoTo', params={'playerid': 0, 'to': track})


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

    json_call('Playlist.GetItems',
              params={'playlistid': playlistid}
              )
    
    json_call('Player.Open',
              item={'playlistid': playlistid, 'position': 0},
              options={'shuffled': shuffled}
              )
    

def play_radio(**kwargs):
    import random
    clear_playlists()

    dbid = int(kwargs.get('id', xbmc.getInfoLabel('ListItem.DBID')))
   
    json_response = json_call('AudioLibrary.GetSongDetails',
                              params={'properties': ['genre'],'songid': dbid})

    if json_response['result']['songdetails'].get('genre', None):
        genre = json_response['result']['songdetails']['genre']
        genre = random.choice(genre)

    if dbid:
        json_call('Playlist.Add',
              item={'songid': dbid},
              params={'playlistid': 0}
              )

    if genre:
        json_response = json_call('AudioLibrary.GetSongs',
                                params={'properties': ['genre']},
                                sort={'method': 'random'},
                                limit=24,
                                query_filter={'genre': genre}
                                )
        
        for count in json_response['result']['songs']:
            if count.get('songid', None):
                songid = count['songid']
                json_call('Playlist.Add',
                        item={'songid': int(songid)},
                        params={'playlistid': 0}
                        )
    
    json_call('Playlist.GetItems',
              params={'playlistid': 0}
              )

    json_call('Player.Open',
              item={'playlistid': 0, 'position': 0}
              )


def rate_song(**kwargs):
    dbid = int(kwargs.get('id', False))
    rating_threshold = int(kwargs.get('rating', 7))
    
        
    json_call('AudioLibrary.SetSongDetails', params={'songid': dbid, 'userrating': rating_threshold})
            
    player = xbmc.Player()
    player_dbid = int(xbmc.getInfoLabel('MusicPlayer.DBID')) if player.isPlayingAudio() else None

    if dbid == player_dbid:
        if rating_threshold is not 0:
            window_property('MusicPlayer_UserRating',set_property=rating_threshold)
        else:
            window_property('MusicPlayer_UserRating', clear_property=True)
        '''
        player_path = player.getPlayingFile()
        item = xbmcgui.ListItem(path=player_path)
        musicInfoTag = item.getMusicInfoTag()
        musicInfoTag.setUserRating(rating_threshold)
        player.updateInfoTag(item)
        '''

def return_label(**kwargs):
    import urllib.parse

    label = kwargs.get('label', False)
    find = kwargs.get('find', False)
    replace = kwargs.get('replace', False)

    if find and replace:
        count = label.count(find) - 1 
        label = label.replace(urllib.parse.unquote(find),
                              urllib.parse.unquote(replace),
                              count)
    else:
        count = label.count('.')
        label = label.replace('.',' ',count - 1).replace('_',' ')

    window_property('Return_Label', set_property=label)


def shuffle_artist(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    json_call('Player.Open', item={
              'artistid': dbid}, options={'shuffled': True})


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

    window_property(name, set_property=random.strip())
    return random