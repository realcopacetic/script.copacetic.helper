#!/usr/bin/python

JSON_MAP = {
    'movie_properties': [
        "title",
        "genre",
        "year",
        "rating",
        "director",
        "trailer",
        "tagline",
        "plot",
        "plotoutline",
        "originaltitle",
        "lastplayed",
        "playcount",
        "writer",
        "studio",
        "mpaa",
        "cast",
        "country",
        "imdbnumber",
        "runtime",
        "set",
        "showlink",
        "streamdetails",
        "top250",
        "votes",
        "fanart",
        "thumbnail",
        "file",
        "sorttitle",
        "resume",
        "setid",
        "dateadded",
        "tag",
        "art",
        "userrating",
        "ratings",
        "premiered",
        "uniqueid"
    ],

    'episode_properties': [
        'title',
        'playcount',
        'season',
        'episode',
        'showtitle',
        'originaltitle',
        'plot',
        'votes',
        'file',
        'rating',
        'ratings',
        'userrating',
        'resume',
        'tvshowid',
        'firstaired',
        'art',
        'streamdetails',
        'runtime',
        'director',
        'writer',
        'cast',
        'dateadded',
        'lastplayed'
    ],

    'season_properties': [
        'season',
        'episode',
        'art',
        'userrating',
        'watchedepisodes',
        'showtitle',
        'playcount',
        'tvshowid'
    ],

    'tvshow_properties': [
        "title",
        "genre",
        "year",
        "rating",
        "plot",
        "studio",
        "mpaa",
        "cast",
        "playcount",
        "episode",
        "imdbnumber",
        "premiered",
        "votes",
        "lastplayed",
        "fanart",
        "thumbnail",
        "file",
        "originaltitle",
        "sorttitle",
        "episodeguide",
        "season",
        "watchedepisodes",
        "dateadded",
        "tag",
        "art",
        "userrating",
        "ratings",
        "runtime",
        "uniqueid"
    ],

    'playlist_properties': [
        'title',
        'artist',
        'albumartist',
        'genre',
        'year',
        'rating',
        'album',
        'track',
        'duration',
        'comment',
        'lyrics',
        'musicbrainztrackid',
        'musicbrainzartistid',
        'musicbrainzalbumid',
        'musicbrainzalbumartistid',
        'playcount',
        'fanart',
        'director',
        'trailer',
        'tagline',
        'plot',
        'plotoutline',
        'originaltitle',
        'lastplayed',
        'writer',
        'studio',
        'mpaa',
        'cast',
        'country',
        'imdbnumber',
        'premiered',
        'productioncode',
        'runtime',
        'set',
        'showlink',
        'streamdetails',
        'top250',
        'votes',
        'firstaired',
        'season',
        'episode',
        'showtitle',
        'thumbnail',
        'file',
        'resume',
        'artistid',
        'albumid',
        'tvshowid',
        'setid',
        'watchedepisodes',
        'disc',
        'tag',
        'art',
        'genreid',
        'displayartist',
        'albumartistid',
        'description',
        'theme',
        'mood',
        'style',
        'albumlabel',
        'sorttitle',
        'episodeguide',
        'uniqueid',
        'dateadded',
        'channel',
        'channeltype',
        'hidden',
        'locked',
        'channelnumber',
        'starttime',
        'endtime',
        'specialsortseason',
        'specialsortepisode',
        'compilation',
        'releasetype',
        'albumreleasetype',
        'contributors',
        'displaycomposer',
        'displayconductor',
        'displayorchestra',
        'displaylyricist',
        'userrating'
    ],

    'artist_properties': [
        'instrument',
        'style',
        'mood',
        'born',
        'formed',
        'description',
        'genre',
        'died',
        'disbanded',
        'yearsactive',
        'musicbrainzartistid',
        'fanart',
        'thumbnail',
        'compilationartist',
        'dateadded',
        'roles',
        'songgenres',
        'isalbumartist'
    ],

    'musicvideo_properties': [
        'title',
        'artist',
        'album',
        'year',
        'premiered',
        'genre',
        'director',
        'plot',
        'resume',
        'art',
        'streamdetails',
        'fanart',
        'thumbnail',
        'runtime',
        'file',
        'playcount',
        'lastplayed',
        'dateadded'
    ]
}