# author: realcopacetic

TMDB_FIELD_MAP = {
    "tvshow": {
        "endpoint": "/tv/{id}",
        "fields": {
            "tagline": ("tagline",),
            "next_episode_to_air": ("next_episode_to_air"),
        },
    },
    "movie": {
        "endpoint": "/movie/{id}",
        "fields": {
            "budget": ("budget",),
            "revenue": ("revenue",),
        },
    },
    "season": {
        "endpoint": "/tv/{id}/season/{season_number}",
        "fields": {
            "overview": ("overview",),
        },
    },
}
