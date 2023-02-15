#!/usr/bin/python
# coding: utf-8


import xbmc
import xbmcgui
from resources.lib.helper import *
from resources.lib.json_map import *


def add_items(li, json_query, type):
    for item in json_query:
        if type == 'movie':
            handle_movies(li, item)
        elif type == 'tvshow':
            handle_tvshows(li, item)
        elif type == 'episode':
            handle_episodes(li, item)
        elif type == 'musicvideo':
            handle_musicvideos(li, item)


def handle_movies(li, item):
    li_item = xbmcgui.ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setDbId(item['movieid'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('movie')
    videoInfoTag.setOriginalTitle(item['originaltitle'])
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setTrailer(item['trailer'])
    videoInfoTag.setYear(item['year'])
    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultMovies.png'})

    for key, value in iter(list(item['streamdetails'].items())):
        for stream in value:
            if 'video' in key:
                videostream = xbmc.VideoStreamDetail(**stream)
                videoInfoTag.addVideoStream(videostream)
            elif 'audio' in key:
                audiostreamlist = list(stream.values())
                audiostream = xbmc.AudioStreamDetail(*audiostreamlist)
                videoInfoTag.addAudioStream(audiostream)

    li.append((item['file'], li_item, False))


def handle_tvshows(li, item):
    dbid = item['tvshowid']
    season = item['season']
    episode = int(item['episode'])
    watchedepisodes = int(item['watchedepisodes'])
    item['file'] = f'videodb://tvshows/titles/{dbid}/'

    li_item = xbmcgui.ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setDbId(item['tvshowid'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('tvshow')
    videoInfoTag.setOriginalTitle(item['originaltitle'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setYear(item['year'])

    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultTVShows.png'})

    watchedepisodepercent = int(((watchedepisodes / episode) * 100)) if episode > 0 and watchedepisodes > 0 else 0
    unwatchedepisodes = int(episode - watchedepisodes) if episode > watchedepisodes else 0

    li_item.setProperty('totalseasons', str(season))
    li_item.setProperty('totalepisodes', str(episode))
    li_item.setProperty('watchedepisodes', str(watchedepisodes))
    li_item.setProperty('unwatchedepisodes', str(unwatchedepisodes))
    li_item.setProperty('watchedepisodepercent', str(watchedepisodepercent))

    li.append((item['file'], li_item, True))


def handle_episodes(li, item):

    episode_number = f"0{item['episode']}" if item['episode'] < 10 else item['episode']
    label = f"{item['season']}x{episode_number}"

    li_item = xbmcgui.ListItem(label, offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setMediaType('episode')
    videoInfoTag.setDbId(item['episodeid'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setEpisode(item['episode'])
    videoInfoTag.setSeason(item['season'])
    videoInfoTag.setTvShowTitle(item['showtitle'])
    videoInfoTag.setPremiered(item['firstaired'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])
    videoInfoTag.setPlaycount(item['playcount'])

    for key, value in iter(list(item['streamdetails'].items())):
        for stream in value:
            if 'video' in key:
                videostream = xbmc.VideoStreamDetail(**stream)
                videoInfoTag.addVideoStream(videostream)
            elif 'audio' in key:
                audiostreamlist = list(stream.values())
                audiostream = xbmc.AudioStreamDetail(*audiostreamlist)
                videoInfoTag.addAudioStream(audiostream)

    li_item.setArt({'icon': 'DefaultTVShows.png',
                    'fanart': item['art'].get('tvshow.fanart', ''),
                    'poster': item['art'].get('tvshow.poster', ''),
                    'banner': item['art'].get('tvshow.banner', ''),
                    'clearlogo': item['art'].get('tvshow.clearlogo') or item['art'].get('tvshow.logo') or '',
                    'landscape': item['art'].get('tvshow.landscape', ''),
                    'clearart': item['art'].get('tvshow.clearart', '')
                    })
    li_item.setArt(item['art'])

    li.append((item['file'], li_item, False))


def handle_musicvideos(li, item):

    li_item = xbmcgui.ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setMediaType('musicvideo')
    videoInfoTag.setDbId(item['musicvideoid'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setArtists(item['artist'])
    videoInfoTag.setYear(item['year'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])

    for key, value in iter(list(item['streamdetails'].items())):
        for stream in value:
            if 'video' in key:
                videostream = xbmc.VideoStreamDetail(**stream)
                videoInfoTag.addVideoStream(videostream)
            elif 'audio' in key:
                audiostreamlist = list(stream.values())
                audiostream = xbmc.AudioStreamDetail(*audiostreamlist)
                videoInfoTag.addAudioStream(audiostream)

    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultVideo.png'})

    li.append((item['file'], li_item, False))
    