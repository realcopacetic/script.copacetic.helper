# author: realcopacetic

from resources.lib.builders.modules import (
    controlsBuilder,
    expressionsBuilder,
    skinsettingsBuilder,
    variablesBuilder,
)
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.xml import XMLHandler
from resources.lib.shared.utilities import EXPRESSIONS, SKINSETTINGS, VARIABLES

BUILDER_CONFIG = {
    "controls": {
        "module": controlsBuilder,
        "dynamic_key": {"id": "id_start"},
        "run_contexts": ["runtime"],
        "file_type": None,
        "file_path": None,
        "file_handler": None,
        "write_kwargs": {},
    },
    "expressions": {
        "module": expressionsBuilder,
        "dynamic_key": {"item": "items"},
        "run_contexts": ["startup", "runtime"],
        "file_type": "xml",
        "file_path": EXPRESSIONS,
        "file_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "expression",
            "transform_func": XMLHandler._dict_to_xml,
        },
    },
    "skinsettings": {
        "module": skinsettingsBuilder,
        "dynamic_key": {},
        "run_contexts": ["buildtime"],
        "file_type": "json",
        "file_path": SKINSETTINGS,
        "file_handler": JSONHandler,
        "write_kwargs": {},
    },
    "variables": {
        "module": variablesBuilder,
        "dynamic_key": {"index": "index"},
        "run_contexts": ["buildtime"],
        "file_type": "xml",
        "file_path": VARIABLES,
        "file_handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "variable",
            "sub_element_name": "value",
            "transform_func": XMLHandler._dict_to_xml,
        },
    },
}
