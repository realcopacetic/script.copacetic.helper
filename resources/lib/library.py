#!/usr/bin/python
# coding: utf-8


import xbmc
import xbmcgui
from resources.lib.utilities import *
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
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setTrailer(item['trailer'])
    videoInfoTag.setYear(item['year'])

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
    li_item.setArt({'icon': 'DefaultMovies.png'})
    li.append((item['file'], li_item, False))


def handle_tvshows(li, item):
    season = item['season']
    episode = int(item['episode'])
    watchedepisodes = int(item['watchedepisodes'])

    li_item = xbmcgui.ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setDbId(item['tvshowid'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('tvshow')
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setYear(item['year'])

    watchedepisodepercent = int(((watchedepisodes / episode) * 100)) if episode > 0 and watchedepisodes > 0 else 0
    unwatchedepisodes = int(episode - watchedepisodes) if episode > watchedepisodes else 0

    li_item.setProperty('totalseasons', str(season))
    li_item.setProperty('totalepisodes', str(episode))
    li_item.setProperty('watchedepisodes', str(watchedepisodes))
    li_item.setProperty('unwatchedepisodes', str(unwatchedepisodes))
    li_item.setProperty('watchedepisodepercent', str(watchedepisodepercent))

    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultTVShows.png'})
    li.append((item['file'], li_item, True))


def handle_episodes(li, item):
    episode_number = f"0{item['episode']}" if item['episode'] < 10 else item['episode']
    label = f"{item['season']}x{episode_number}"

    li_item = xbmcgui.ListItem(label, offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setDbId(item['episodeid'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setEpisode(item['episode'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('episode')
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setPremiered(item['firstaired'])
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])
    videoInfoTag.setSeason(item['season'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setTvShowTitle(item['showtitle'])

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
    li_item.setArt({'icon': 'DefaultTVShows.png'})
    li.append((item['file'], li_item, False))


def handle_musicvideos(li, item):
    li_item = xbmcgui.ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()

    videoInfoTag.setArtists(item['artist'])
    videoInfoTag.setDbId(item['musicvideoid'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('musicvideo')
    videoInfoTag.setResumePoint(item['resume']['position'], item['resume']['total'])
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setYear(item['year'])
    
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
    