#!/usr/bin/python
# coding: utf-8
from resources.lib.utilities import *


def get_default_settings(**kwargs):
    settings = {
        'filelists.showparentdiritems': False,
        'videolibrary.showallitems': False,
        'videolibrary.groupmoviesets': True,
        'videolibrary.flattentvshows': 1,
        'videolibrary.showemptytvshows': False,
        'videolibrary.tvshowsselectfirstunwatcheditem': 2,
        'videolibrary.tvshowsincludeallseasonsandspecials': 3,
        'videolibrary.artworklevel': 2,
        'videolibrary.movieartwhitelist': ['clearlogo', 'clearlogo-alt', 'clearlogo-aligned', 'clearlogo-alt-aligned', 'clearlogo-billboard', 'keyart', 'square'],
        'videolibrary.tvshowartwhitelist': ['clearlogo', 'clearlogo-alt', 'clearlogo-aligned', 'clearlogo-alt-aligned', 'clearlogo-billboard', 'keyart', 'square'],
        'musiclibrary.showallitems': False,
        'musiclibrary.showcompilationartists': False,
        'pictures.generatethumbs': True,
        'musicplayer.visualisation': 'visualisation.waveform'
    }
    settings_to_change = {}
    for item in settings.items():
        window_property(key=item[0], clear_property=True)
        if 'artwhitelist' not in item[0] or settings_to_change.get('videolibrary.artworklevel') is None:
            json_response = json_call('Settings.GetSettingValue',
                                      params={'setting': item[0]},
                                      parent='copacetic_settings'
                                      )    
            json_response = json_response['result']['value']
        else:
            json_response = item[1]

        if json_response != item[1] or ('artwhitelist' in item[0] and settings_to_change.get('videolibrary.artworklevel') != 2):
            settings_to_change.update({item[0]: json_response})
            if isinstance(item[1], list):
                window_property(key=item[0], set_property=', '.join(json_response))
            else:
                window_property(key=item[0], set_property=f'{json_response}')
    log(f"HOLA {settings_to_change}")


def clean_filename(label, **kwargs):
    json_response = json_call('Settings.GetSettingValue',
                              params={'setting': 'filelists.showextensions'},
                              parent='clean_filename'
                              )

    subtraction = 1 if json_response['result']['value'] is True else 0
    count = label.count('.') - subtraction
    label = label.replace('.', ' ', count).replace('_', ' ').strip()

    window_property('Return_Label', set_property=label)


def dialog_yesno(heading, message, **kwargs):
    yes_actions = kwargs.get('yes_actions', '').split('|')
    no_actions = kwargs.get('no_actions', 'Null').split('|')

    if DIALOG.yesno(heading, message):
        for action in yes_actions:
            log_and_execute(action)
    else:
        for action in no_actions:
            log_and_execute(action)


def hex_contrast_check(**kwargs):
    hex = kwargs.get('hex',False)
    
    if hex:
        r = int(hex[2:-4], 16)
        g = int(hex[4:-2], 16)
        b = int(hex[6:], 16)
        
        #Credit to Mark Ransom: https://stackoverflow.com/questions/3942878/how-to-decide-font-color-in-white-or-black-depending-on-background-color
        #Simple formula...
        #best_contrast = 'dark' if (r * 0.299 + g * 0.587 + b * 0.114) > 186 else 'light'
        #Complex formula...

        rgb = [r, g, b]
        new_rgb = []

        for c in rgb:
            c = c / 255.0
            if c <= 0.04045:
                c = c / 12.92
            else:
                pow(((c + 0.055) / 1.055), 2.4)
            new_rgb.append(c)
        
        r = new_rgb[0]
        g = new_rgb[1]
        b = new_rgb[2]
        
        luminosity = 0.2126 * r + 0.7152 * g + 0.0722 * b
        best_contrast = 'dark' if luminosity > 0.179 else 'light'

        xbmc.executebuiltin(f'Skin.SetString(Accent_Color_Contrast,{best_contrast})')

            
def play_album(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    if dbid:
        json_call('Player.Open', 
                  item={'albumid': dbid}, 
                  options={'shuffled': False},
                  parent='play_album'
                  )


def play_album_from_track(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    track = int(kwargs.get('track', False)) - 1

    if dbid:
        json_response = json_call('AudioLibrary.GetSongDetails',
                                  params={'properties': ['albumid'],'songid': dbid},
                                  parent='play_album_from_track'
                                  )

    if json_response['result'].get('songdetails', None):
        albumid = json_response['result']['songdetails']['albumid']

    json_call('Player.Open',
              item={'albumid': albumid},
              options={'shuffled': False},
              parent='play_album_from_track'
              )
    
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

        dbid = int(xbmc.getInfoLabel(f'{method}({count}).DBID'))
        url = xbmc.getInfoLabel(f'{method}({count}).Filenameandpath')

        if media_type and dbid:
            json_call('Playlist.Add',
                      item={f'{media_type}id': dbid},
                      params={'playlistid': playlistid},
                      parent='play_items'
                      )
        elif url:
            json_call('Playlist.Add',
                      item={'file': url},
                      params={'playlistid': playlistid},
                      parent='play_items'
                      )

    json_call('Playlist.GetItems',
              params={'playlistid': playlistid},
              parent='play_items'
              )
    
    json_call('Player.Open',
              item={'playlistid': playlistid, 'position': 0},
              options={'shuffled': shuffled},
              parent='play_items'
              )
    

def play_radio(**kwargs):
    import random
    clear_playlists()

    dbid = int(kwargs.get('id', xbmc.getInfoLabel('ListItem.DBID')))

    json_response = json_call('AudioLibrary.GetSongDetails',
                              params={'properties': ['genre'],'songid': dbid},
                              parent='play_radio'
                              )

    if json_response['result']['songdetails'].get('genre', None):
        genre = json_response['result']['songdetails']['genre']
        genre = random.choice(genre)

    if genre:
        json_call('Playlist.Add',
                  item={'songid': dbid},
                  params={'playlistid': 0},
                  parent='play_radio'
                  )
        
        json_response = json_call('AudioLibrary.GetSongs',
                                params={'properties': ['genre']},
                                sort={'method': 'random'},
                                limit=24,
                                query_filter={'genre': genre},
                                parent='play_radio'
                                )
        
        for count in json_response['result']['songs']:
            if count.get('songid', None):
                songid = int(count['songid'])

                json_call('Playlist.Add',
                        item={'songid': songid},
                        params={'playlistid': 0},
                        parent='play_radio'
                        )

        json_call('Playlist.GetItems',
                params={'playlistid': 0},
                parent='play_radio'
                )

        json_call('Player.Open',
                item={'playlistid': 0, 'position': 0},
                parent='play_radio'
                )


def rate_song(**kwargs):
    dbid = int(kwargs.get('id', xbmc.getInfoLabel('ListItem.DBID')))
    rating_threshold = int(kwargs.get('rating',xbmc.getInfoLabel('Skin.String(Music_Rating_Like_Threshold)')))
        
    json_call('AudioLibrary.SetSongDetails',
              params={'songid': dbid, 'userrating': rating_threshold},
              parent='rate_song'
              )
            
    player = xbmc.Player()
    player_dbid = int(xbmc.getInfoLabel('MusicPlayer.DBID')) if player.isPlayingAudio() else None

    if dbid == player_dbid:
        if rating_threshold != 0:
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

def return_label(property=True, **kwargs):

    label = kwargs.get('label', xbmc.getInfoLabel('ListItem.Label'))
    find = kwargs.get('find', '.')
    replace = kwargs.get('replace', ' ')
    
    count = label.count(find)
    label = label.replace(urllib.unquote(find),
                          urllib.unquote(replace),
                          count)        
    if property:
        window_property('Return_Label', set_property=label)
    else:
        return label


def shuffle_artist(**kwargs):
    clear_playlists()

    dbid = int(kwargs.get('id', False))
    json_call('Player.Open',
              item={'artistid': dbid},
              options={'shuffled': True},
              parent='shuffle_artist')


def split(string, **kwargs):
    separator = kwargs.get('separator', ' / ')
    name = kwargs.get('name', 'Split')

    for count, value in enumerate(string.split(separator)):
        window_property(f'{name}.{count}', set_property=value)


def split_random_return(string, **kwargs):
    import random

    separator = kwargs.get('separator', ' / ')
    name = kwargs.get('name', 'SplitRandomReturn') 
    string = random.choice(string.split(separator))
    random = random.choice(string.split(' & '))
    random = return_label(label=random, find='-',replace=' ', property=False) if random != 'Sci-Fi' else random
    random = random.strip()
    
    window_property(name, set_property=random)
    return random