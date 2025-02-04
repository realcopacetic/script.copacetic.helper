# author: realcopacetic, sualfred

from resources.lib.plugin.json_map import JSON_MAP
from resources.lib.plugin.library import *
from resources.lib.utilities import (ADDON, condition, infolabel, json_call, log,
                                     set_plugincontent)


class PluginContent(object):
    def __init__(self, params, li):
        self.dbtitle = params.get('title')
        self.dbtype = params.get('type')
        self.dbid = params.get('id')
        self.limit = params.get('limit')
        self.label = params.get('label')
        self.target = params.get('target')
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

        self.filter_unwatched = {'field': 'playcount',
                                 'operator': 'lessthan', 'value': '1'}
        self.filter_watched = {'field': 'playcount',
                               'operator': 'greaterthan', 'value': '0'}
        self.filter_unwatched_episodes = {
            'field': 'numwatched', 'operator': 'lessthan', 'value': ['1']}
        self.filter_watched_episodes = {
            'field': 'numwatched', 'operator': 'greaterthan', 'value': ['0']}
        self.filter_no_specials = {'field': 'season',
                                   'operator': 'greaterthan', 'value': '0'}
        self.filter_inprogress = {
            'field': 'inprogress', 'operator': 'true', 'value': ''}
        self.filter_not_inprogress = {
            'field': 'inprogress', 'operator': 'false', 'value': ''}
        self.filter_title = {'field': 'title',
                             'operator': 'is', 'value': self.dbtitle}
        self.filter_director = {'field': 'director',
                                'operator': 'is', 'value': self.label}
        self.filter_actor = {'field': 'actor',
                             'operator': 'is', 'value': self.label}
        if self.exclude_value:
            self.filter_exclude = {'field': self.exclude_key,
                                   'operator': 'isnot', 'value': self.exclude_value}

    def helper(self):
        log(f'FUCK75_', force=True)
        resume = {'position': 0, 'total': 100}
        progress_types = [
            'ListItem.PercentPlayed',
            'ListItem.Property(WatchedEpisodePercent)'
        ]
        for type in progress_types:
            position = infolabel(type)
            if position:
                log(f'FUCK99_{position}', force=True)
                resume['position'] = int(position)
                break
        else:
            if 'set' in self.dbtype:
                log(f'FUCK76_', force=True)
                watched = 0
                query = json_call(
                    'VideoLibrary.GetMovieSetDetails',
                    params={'setid': int(self.dbid)},
                    parent='get_set_movies'
                )
                try:
                    total = query['result']['setdetails']['limits']['total']
                    movies = query['result']['setdetails']['movies']
                except KeyError:
                    total = 0
                else:
                    for movie in movies:
                        query = json_call(
                            'VideoLibrary.GetMovieDetails',
                            params={'properties': [
                                'playcount'], 'movieid': movie['movieid']},
                            parent='get_movie_playcounts'
                        )
                        playcount = query['result']['moviedetails'].get('playcount')
                        if playcount:
                            watched += 1
                finally:
                    # https://stackoverflow.com/a/68118106/21112145 to avoid ZeroDivisionError
                    log(f'FUCK77_ {watched} / {total}', force=True)
                    resume['position'] = (total and watched / total or 0) * 100
        data = [{'title': infolabel('ListItem.Label'), 'resume': resume}]
        add_items(self.li, data)
    
    def in_progress(self):
        filters = [self.filter_inprogress]

        if self.dbtype != 'tvshow':
            json_query = json_call('VideoLibrary.GetMovies',
                                   properties=JSON_MAP['movie_properties'],
                                   sort=self.sort_lastplayed,
                                   query_filter={'and': filters},
                                   parent='in_progress'
                                   )
            try:
                json_query = json_query['result']['movies']
            except Exception:
                log('Widget in_progress: No movies found.')
            else:
                add_items(self.li, json_query, type='movie')
        
        if self.dbtype != 'movie':
            json_query = json_call('VideoLibrary.GetEpisodes',
                                   properties=JSON_MAP['episode_properties'],
                                   sort=self.sort_lastplayed,
                                   query_filter={'and': filters},
                                   parent='in_progress'
                                   )
            try:
                json_query = json_query['result']['episodes']
            except Exception:
                log('Widget in_progress: No episodes found.')
            else:
                for episode in json_query:
                    tvshowid = episode.get('tvshowid')
                    tvshow_json_query = json_call(
                        'VideoLibrary.GetTVShowDetails',
                        params={'tvshowid': tvshowid},
                        properties=['studio', 'mpaa'],
                        parent='in_progress'
                    )
                    try:
                        tvshow_json_query = tvshow_json_query['result']['tvshowdetails']
                    except Exception:
                        log(f'Widget in_progress: Parent tv show not found --> {tvshowid}')
                    else:
                        episode['studio'] = tvshow_json_query.get('studio')
                        episode['mpaa'] = tvshow_json_query.get('mpaa')
                add_items(self.li, json_query, type='episode')
        set_plugincontent(content='movies',
                          category=ADDON.getLocalizedString(32601))

    def next_up(self):
        filters = [self.filter_inprogress]

        json_query = json_call('VideoLibrary.GetTVShows',
                               properties=['title', 'lastplayed',
                                           'studio', 'mpaa'],
                               sort=self.sort_lastplayed, limit=25,
                               query_filter={'and': filters},
                               parent='next_up'
                               )

        try:
            json_query = json_query['result']['tvshows']
        except Exception:
            log('Widget next_up: No TV shows found')
            return

        for episode in json_query:
            use_last_played_season = True
            studio = episode.get('studio', '')
            mpaa = episode.get('mpaa', '')
            last_played_query = json_call('VideoLibrary.GetEpisodes',
                                          properties=['seasonid', 'season'],
                                          sort={'order': 'descending', 'method': 'lastplayed'}, limit=1,
                                          query_filter={'and': [
                                              {'or': [self.filter_inprogress, self.filter_watched]}, self.filter_no_specials]},
                                          params={'tvshowid': int(
                                              episode['tvshowid'])},
                                          parent='next_up'
                                          )

            if last_played_query['result']['limits']['total'] < 1:
                use_last_played_season = False

            ''' Return the next episode of last played season'''
            if use_last_played_season:
                episode_query = json_call('VideoLibrary.GetEpisodes',
                                          properties=JSON_MAP['episode_properties'],
                                          sort={'order': 'ascending', 'method': 'episode'}, limit=1,
                                          query_filter={'and': [self.filter_unwatched, {'field': 'season', 'operator': 'is', 'value': str(
                                              last_played_query['result']['episodes'][0].get('season'))}]},
                                          params={'tvshowid': int(
                                              episode['tvshowid'])},
                                          parent='next_up'
                                          )

                if episode_query['result']['limits']['total'] < 1:
                    use_last_played_season = False

            ''' If no episode is left of the last played season, fall back to the very first unwatched episode'''
            if not use_last_played_season:
                episode_query = json_call('VideoLibrary.GetEpisodes',
                                          properties=JSON_MAP['episode_properties'],
                                          sort={'order': 'ascending', 'method': 'episode'}, limit=1,
                                          query_filter={
                                              'and': [self.filter_unwatched, self.filter_no_specials]},
                                          params={'tvshowid': int(
                                              episode['tvshowid'])},
                                          parent='next_up'
                                          )

            try:
                episode_details = episode_query['result']['episodes']
                ''' Add tv show studio and mpaa to episode dictionary '''
                episode_details[0]['studio'] = studio
                episode_details[0]['mpaa'] = mpaa
            except Exception:
                log(
                    f"Widget next_up: No next episodes found for {episode['title']}")
            else:
                add_items(self.li, episode_details, type='episode')
                set_plugincontent(content='episodes',
                                  category=ADDON.getLocalizedString(32600))

    def director_credits(self):
        filters = [self.filter_director]
        if self.filter_exclude:
            filters.append(self.filter_exclude)

        json_query = json_call('VideoLibrary.GetMovies',
                               properties=JSON_MAP['movie_properties'],
                               sort=self.sort_year,
                               query_filter={'and': filters},
                               parent='director_credits'
                               )

        try:
            json_query = json_query['result']['movies']
        except Exception:
            log('Widget director_credits: No movies found.')
        else:
            add_items(self.li, json_query, type='movie')

        json_query = json_call('VideoLibrary.GetMusicVideos',
                               properties=JSON_MAP['musicvideo_properties'],
                               sort=self.sort_year,
                               query_filter={'and': filters},
                               parent='director_credits'
                               )

        try:
            json_query = json_query['result']['musicvideos']
        except Exception:
            log('Widget director_credits: No music videos found.')
        else:
            add_items(self.li, json_query, type='musicvideo')

        set_plugincontent(content='videos',
                          category=ADDON.getLocalizedString(32602))

    def actor_credits(self):
        filters = [self.filter_actor]
        # grab current movie or tvshow name
        if condition('String.IsEqual(ListItem.DBType,episode)'):
            current_item = infolabel('ListItem.TVShowTitle')
        else:
            current_item = infolabel('ListItem.Label')
        # json lookup for movies and tvshows by given actor
        movies_json_query = json_call('VideoLibrary.GetMovies',
                                      properties=JSON_MAP['movie_properties'],
                                      sort=self.sort_year,
                                      query_filter={'and': filters},
                                      parent='actor_credits'
                                      )

        tvshows_json_query = json_call('VideoLibrary.GetTVShows',
                                       properties=JSON_MAP['tvshow_properties'],
                                       sort=self.sort_year,
                                       query_filter={'and': filters},
                                       parent='actor_credits'
                                       )
        # work out combined number of movie/tvshow credits
        total_items = int(movies_json_query['result']['limits']['total']) + int(
            tvshows_json_query['result']['limits']['total'])

        # if there are movie results, remove the current item if it is in the list, then add the remaining to the plugin directory
        try:
            movies_json_query = movies_json_query['result']['movies']
        except Exception:
            log(f'Widget actor_credits: No movies found for {self.label}.')
        else:
            dict_to_remove = next(
                (item for item in movies_json_query if item['label'] == current_item), None)
            movies_json_query.remove(
                dict_to_remove) if dict_to_remove is not None and total_items > 1 else None
            add_items(self.li, movies_json_query, type='movie')
        # if there are tvshow results, remove the current item if it is in the list, then add the remaining to the plugin directory
        try:
            tvshows_json_query = tvshows_json_query['result']['tvshows']
        except Exception:
            log(f'Widget actor_credits: No tv shows found for {self.label}.')
        else:
            dict_to_remove = next(
                (item for item in tvshows_json_query if item['label'] == current_item), None)
            tvshows_json_query.remove(
                dict_to_remove) if dict_to_remove is not None and total_items > 1 else None
            add_items(self.li, tvshows_json_query, type='tvshow')

        set_plugincontent(content='videos',
                          category=ADDON.getLocalizedString(32603))
