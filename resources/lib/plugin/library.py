# author: realcopacetic, sualfred

import xbmc
from xbmcgui import ListItem


def add_items(li, json_query, type='helper'):
    for item in json_query:
        if type == 'movie':
            set_movie(li, item)
        elif type == 'tvshow':
            set_tvshow(li, item)
        elif type == 'episode':
            set_episode(li, item)
        elif type == 'musicvideo':
            set_musicvideo(li, item)
        else:
            set_helper(li, item)


def set_helper(li, item):
    li_item = ListItem(item['title'], offscreen=True)
    li_item.setProperty('unwatchedepisodes', item['unwatchedepisodes'])
    li_item.setArt(item['art']) if item.get('art') else None
    videoInfoTag = li_item.getVideoInfoTag()
    videoInfoTag.setDirectors([item['director']])
    videoInfoTag.setGenres([item['genre']])
    videoInfoTag.setResumePoint(
        item['resume']['position'], item['resume']['total']
    )
    videoInfoTag.setStudios([item['studio']])
    videoInfoTag.setWriters([item['writer']])
    li.append(('file', li_item, False))

def set_movie(li, item):
    li_item = ListItem(item['title'], offscreen=True)
    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultMovies.png'})
    videoInfoTag = li_item.getVideoInfoTag()
    videoInfoTag.setDbId(item['movieid'])
    videoInfoTag.setDirectors(item['director'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMpaa(item['mpaa'])
    videoInfoTag.setMediaType('movie')
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setPlot(item['plot'])
    videoInfoTag.setPlotOutline(item['plotoutline'])
    videoInfoTag.setResumePoint(
        item['resume']['position'], item['resume']['total']
    )
    videoInfoTag.setStudios(item['studio'])
    videoInfoTag.setTagLine(item['tagline'])
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
    li.append((item['file'], li_item, False))


def set_tvshow(li, item):
    season = item['season']
    episode = int(item['episode'])
    watchedepisodes = int(item['watchedepisodes'])
    # watchedepisodepercent
    if episode > 0 and watchedepisodes > 0:
        watchedepisodepercent = int(((watchedepisodes / episode) * 100))
    else:
        watchedepisodepercent = 0
    # unwatchedepisodes
    if episode > watchedepisodes:
        unwatchedepisodes = int(episode - watchedepisodes)
    else:
        unwatchedepisodes = 0
    li_item.setProperty('totalseasons', str(season))
    li_item.setProperty('totalepisodes', str(episode))
    li_item.setProperty('watchedepisodes', str(watchedepisodes))
    li_item.setProperty('unwatchedepisodes', str(unwatchedepisodes))
    li_item.setProperty('watchedepisodepercent', str(watchedepisodepercent))
    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultTVShows.png'})
    li_item = ListItem(item['title'], offscreen=True)
    videoInfoTag = li_item.getVideoInfoTag()
    videoInfoTag.setDbId(item['tvshowid'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('tvshow')
    videoInfoTag.setMpaa(item['mpaa'])
    videoInfoTag.setStudios(item['studio'])
    videoInfoTag.setTitle(item['title'])
    videoInfoTag.setYear(item['year'])
    li.append((item['file'], li_item, True))


def set_episode(li, item):
    if item['episode'] < 10:
        episode_number = f"0{item['episode']}"
    else:
        episode_number = item['episode']
    label = f"{item['season']}x{episode_number}"
    li_item = ListItem(label, offscreen=True)
    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultTVShows.png'})
    videoInfoTag = li_item.getVideoInfoTag()
    videoInfoTag.setDbId(item['episodeid'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setEpisode(item['episode'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('episode')
    videoInfoTag.setMpaa(item['mpaa'])
    videoInfoTag.setPlaycount(item['playcount'])
    videoInfoTag.setPremiered(item['firstaired'])
    videoInfoTag.setResumePoint(
        item['resume']['position'], item['resume']['total']
    )
    videoInfoTag.setSeason(item['season'])
    videoInfoTag.setStudios(item['studio'])
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
    li.append((item['file'], li_item, False))


def set_musicvideo(li, item):
    li_item = ListItem(item['title'], offscreen=True)
    li_item.setArt(item['art'])
    li_item.setArt({'icon': 'DefaultVideo.png'})
    videoInfoTag = li_item.getVideoInfoTag()
    videoInfoTag.setArtists(item['artist'])
    videoInfoTag.setDbId(item['musicvideoid'])
    videoInfoTag.setDuration(item['runtime'])
    videoInfoTag.setLastPlayed(item['lastplayed'])
    videoInfoTag.setMediaType('musicvideo')
    videoInfoTag.setResumePoint(
        item['resume']['position'], item['resume']['total']
    )
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
    li.append((item['file'], li_item, False))
