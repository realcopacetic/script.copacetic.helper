#!/usr/bin/python
# coding: utf-8


from resources.lib.helper import *
from resources.lib.json_map import *
from resources.lib.library import *


class PluginContent(object):
    def __init__(self, params, li):
        self.dbtitle = params.get('title')
        self.dbtype = params.get('type')
        self.limit = params.get('limit')
        self.label = params.get('label')
        self.exclude_key = params.get('exclude_key')
        self.exclude_value = params.get('exclude_value')
        self.li = li

        if not self.exclude_key:
            self.exclude_key = 'title'

        if self.limit:
            self.limit = int(self.limit)

        if self.dbtype:
            if self.dbtype in ['movie', 'tvshow', 'season', 'episode', 'musicvideo']:
                library = 'Video'
            else:
                library = 'Audio'

            self.method_details = f'{library}Library.Get{self.dbtype}Details'
            self.method_item = f'{library}Library.Get{self.dbtype}s'
            self.param = f'{self.dbtype}id'
            self.key_details = f'{self.dbtype}details'
            self.key_items = f'{self.dbtype}s'
            self.properties = JSON_MAP.get(f'{self.dbtype}_properties')

        self.sort_lastplayed = {'order': 'descending', 'method': 'lastplayed'}
        self.sort_recent = {'order': 'descending', 'method': 'dateadded'}
        self.sort_year = {'order': 'descending', 'method': 'year'}
        self.sort_random = {'method': 'random'}

        self.filter_unwatched = {'field': 'playcount', 'operator': 'lessthan', 'value': '1'}
        self.filter_watched = {'field': 'playcount', 'operator': 'greaterthan', 'value': '0'}
        self.filter_unwatched_episodes = {'field': 'numwatched', 'operator': 'lessthan', 'value': ['1']}
        self.filter_watched_episodes = {'field': 'numwatched', 'operator': 'greaterthan', 'value': ['0']}
        self.filter_no_specials = {'field': 'season', 'operator': 'greaterthan', 'value': '0'}
        self.filter_inprogress = {'field': 'inprogress', 'operator': 'true', 'value': ''}
        self.filter_not_inprogress = {'field': 'inprogress', 'operator': 'false', 'value': ''}
        self.filter_title = {'field': 'title', 'operator': 'is', 'value': self.dbtitle}
        self.filter_director = {'field': 'director', 'operator': 'is', 'value': self.label}
        if self.exclude_value:
            self.filter_exclude = {'field': self.exclude_key,'operator': 'isnot', 'value': self.exclude_value}
        
    def getinprogress(self):
        filters = [self.filter_inprogress]

        if self.dbtype != 'tvshow':
            json_query = json_call('VideoLibrary.GetMovies',
                                   properties=JSON_MAP['movie_properties'],
                                   sort=self.sort_lastplayed,
                                   query_filter={'and': filters}
                                   )
            try:
                json_query = json_query['result']['movies']
            except Exception:
                log('WIDGET getinprogress: No movies found.')
            else:
                add_items(self.li, json_query, type='movie')

        if self.dbtype != 'movie':
            json_query = json_call('VideoLibrary.GetEpisodes',
                                   properties=JSON_MAP['episode_properties'],
                                   sort=self.sort_lastplayed,
                                   query_filter={'and': filters}
                                   )
            try:
                json_query = json_query['result']['episodes']
            except Exception:
                log('WIDGET getinprogress: No episodes found.')
            else:
                add_items(self.li, json_query, type='episode')

        set_plugincontent(content='videos',
                          category=ADDON.getLocalizedString(32013))

    def getnextup(self):
        filters = [self.filter_inprogress]

        json_query = json_call('VideoLibrary.GetTVShows',
                               properties=['title', 'lastplayed'],
                               sort=self.sort_lastplayed, limit=25,
                               query_filter={'and': filters}
                               )

        try:
            json_query = json_query['result']['tvshows']
        except Exception:
            log('WIDGET getnextup: No TV shows found')
            return

        for episode in json_query:
                use_last_played_season = True
                last_played_query = json_call('VideoLibrary.GetEpisodes',
                                              properties=[
                                                  'seasonid', 'season'],
                                              sort={'order': 'descending', 'method': 'lastplayed'}, limit=1,
                                              query_filter={'and': [
                                                  {'or': [self.filter_inprogress, self.filter_watched]}, self.filter_no_specials]},
                                              params={'tvshowid': int(
                                                  episode['tvshowid'])}
                                              )

                if last_played_query['result']['limits']['total'] < 1:
                     use_last_played_season = False

                ''' Return the next episode of last played season
                '''
                if use_last_played_season:
                    episode_query = json_call('VideoLibrary.GetEpisodes',
                                              properties=JSON_MAP['episode_properties'],
                                              sort={'order': 'ascending', 'method': 'episode'}, limit=1,
                                              query_filter={'and': [self.filter_unwatched, {'field': 'season', 'operator': 'is', 'value': str(
                                                  last_played_query['result']['episodes'][0].get('season'))}]},
                                              params={'tvshowid': int(
                                                  episode['tvshowid'])}
                                              )

                    if episode_query['result']['limits']['total'] < 1:
                        use_last_played_season = False

                ''' If no episode is left of the last played season, fall back to the very first unwatched episode
                '''
                if not use_last_played_season:
                    episode_query = json_call('VideoLibrary.GetEpisodes',
                                              properties=JSON_MAP['episode_properties'],
                                              sort={'order': 'ascending', 'method': 'episode'}, limit=1,
                                              query_filter={
                                                  'and': [self.filter_unwatched, self.filter_no_specials]},
                                              params={'tvshowid': int(
                                                  episode['tvshowid'])}
                                              )

                try:
                    episode_details = episode_query['result']['episodes']
                except Exception:
                    log(
                        f"WIDGET getnextup: No next episodes found for {episode['title']}")
                else:
                    add_items(self.li, episode_details, type='episode')
                    set_plugincontent(content='episodes',
                                      category=ADDON.getLocalizedString(32008))

    def getdirector(self):
        filters = [self.filter_director]
        if self.filter_exclude:
            filters.append(self.filter_exclude)

        if self.dbtype != 'musicvideo':
            json_query = json_call('VideoLibrary.GetMovies',
                                   properties=JSON_MAP['movie_properties'],
                                   sort=self.sort_year,
                                   query_filter={'and': filters}
                                   )
            try:
                json_query = json_query['result']['movies']
            except Exception:
                log('WIDGET getdirector: No movies found.')
            else:
                add_items(self.li, json_query, type='movie')

        if self.dbtype != 'movie':
            json_query = json_call('VideoLibrary.GetMusicVideos',
                                   properties=JSON_MAP['musicvideo_properties'],
                                   sort=self.sort_year,
                                   query_filter={'and': filters}
                                   )
            try:
                json_query = json_query['result']['musicvideos']
            except Exception:
                log('WIDGET getdirector: No music videos found.')
            else:
                add_items(self.li, json_query, type='musicvideo')

        set_plugincontent(content='videos',
                          category=ADDON.getLocalizedString(32014))
