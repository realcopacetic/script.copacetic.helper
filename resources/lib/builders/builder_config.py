# author: realcopacetic

from resources.lib.builders.modules import (
    configsBuilder,
    controlsBuilder,
    expressionsBuilder,
    includesBuilder,
    variablesBuilder,
)
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    CONFIGS,
    CONTROLS,
    EXPRESSIONS,
    INCLUDES,
    VARIABLES,
)
from resources.lib.shared.xml import XMLHandler

BUILDER_CONFIG = {
    "configs": {
        "module": configsBuilder,
        "run_contexts": ["prep"],
        "write_type": "json",
        "write_path": CONFIGS,
        "write_handler": JSONHandler,
        "write_kwargs": {},
    },
    "controls": {
        "module": controlsBuilder,
        "run_contexts": ["build"],
        "write_type": "json",
        "write_path": CONTROLS,
        "write_handler": JSONHandler,
        "write_kwargs": {},
    },
    "variables": {
        "module": variablesBuilder,
        "run_contexts": ["build"],
        "write_type": "xml",
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
        "module": includesBuilder,
        "run_contexts": ["build", "runtime"],
        "read_kwargs": {
            "root_tag": "xml",
            "mapping_tag": "mapping",
            "container_tag": "includes",
            "element_tag": "template",
            "sub_element_tag": "include",
        },
        "write_type": "xml",
        "write_path": INCLUDES,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "transform_func": XMLHandler._complex_dict_to_xml,
        },
    },
    "expressions": {
        "module": expressionsBuilder,
        "run_contexts": ["build", "runtime"],
        "write_type": "xml",
        "write_path": EXPRESSIONS,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "expression",
            "transform_func": XMLHandler._simple_dict_to_xml,
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
