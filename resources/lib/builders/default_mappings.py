DEFAULT_MAPPINGS = {
    "default_mappings": {
        "content_types": {
            "items": {
                "addons": ["addons"],
                "favourites": ["favourites"],
                "music": ["artists", "albums", "songs"],
                "pictures": ["images"],
                "videos": [
                    "movies",
                    "sets",
                    "tvshows",
                    "seasons",
                    "episodes",
                    "videos",
                    "musicvideos",
                ],
            },
            "placeholders": {"key": "{window}", "value": "{content_type}"},
        },
        "widgets": {
            "items": ["3201", "3202", "3203"],
            "placeholders": {"key": "{id}"},
        },
    },
    "custom_mappings": ["custom_mapping1.json", "custom_mapping2.json"],
}
