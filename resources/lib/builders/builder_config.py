# author: realcopacetic

from resources.lib.builders.modules import (
    controlsBuilder,
    expressionsBuilder,
    skinsettingsBuilder,
    variablesBuilder,
    xmlBuilder
)
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    CONTROLS,
    ELEMENTS,
    EXPRESSIONS,
    SKINSETTINGS,
    VARIABLES,
)
from resources.lib.shared.xml import XMLHandler


BUILDER_CONFIG = {
    "controls": {
        "module": controlsBuilder,
        "run_contexts": ["buildtime"],
        "write_type": "json",
        "write_path": CONTROLS,
        "write_handler": JSONHandler,
        "write_kwargs": {},
    },
    "expressions": {
        "module": expressionsBuilder,
        "run_contexts": ["startup", "runtime"],
        "write_type": "xml",
        "write_path": EXPRESSIONS,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "expression",
            "transform_func": XMLHandler._dict_to_xml,
        },
    },
    "skinsettings": {
        "module": skinsettingsBuilder,
        "run_contexts": ["buildtime"],
        "write_type": "json",
        "write_path": SKINSETTINGS,
        "write_handler": JSONHandler,
        "write_kwargs": {},
    },
    "variables": {
        "module": variablesBuilder,
        "run_contexts": ["buildtime"],
        "write_type": "xml",
        "write_path": VARIABLES,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "variable",
            "sub_element_tag": "value",
            "transform_func": XMLHandler._dict_to_xml,
        },
    },
    "xml": {
        "module": xmlBuilder,
        "run_contexts": ["buildtime"],
        "read_kwargs": {
          "root_tag": "xml",
          "container_tag": "elements",
          "element_tag": "element"
        },
        "write_type": "xml",
        "write_path": ELEMENTS,
        "write_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_tag": "include",
            "transform_func": XMLHandler._dict_to_xml,
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
