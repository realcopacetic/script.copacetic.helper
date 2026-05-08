# author: realcopacetic

from resources.lib.builders.modules import (
    ExpressionsBuilder,
    IncludesBuilder,
    VariablesBuilder,
)
from resources.lib.shared.utilities import (
    EXPRESSIONS,
    INCLUDES,
    VARIABLES,
)
from resources.lib.shared.xml import XMLHandler, sort_outer_keys

BUILDER_CONFIG = {
    "variables": {
        "module": VariablesBuilder,
        "write_path": VARIABLES,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "variable",
            "sub_element_tag": "value",
            "transform_func": XMLHandler._simple_dict_to_xml,
        },
    },
    "includes": {
        "module": IncludesBuilder,
        "read_kwargs": {
            "root_tag": "xml",
            "mapping_tag": "mapping",
            "container_tag": "includes",
            "element_tag": "template",
            "sub_element_tag": "include",
        },
        "write_path": INCLUDES,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "transform_func": XMLHandler._complex_dict_to_xml,
        },
    },
    "expressions": {
        "module": ExpressionsBuilder,
        "write_path": EXPRESSIONS,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "expression",
            "transform_func": sort_outer_keys(XMLHandler._simple_dict_to_xml),
        },
    },
}

BUILDER_MAPPINGS = {
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
        "placeholders": {"key": "window", "value": "content_type"},
    },
}
