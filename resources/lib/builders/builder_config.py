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
        "file_type": None,
        "file_path": None,
        "handler": None,
        "write_kwargs": {},
        "dynamic_key": {"id": "id_start"},
        "run_contexts": ["runtime"],
    },
    "expressions": {
        "module": expressionsBuilder,
        "file_type": "xml",
        "file_path": EXPRESSIONS,
        "handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "expression",
            "transform_func": XMLHandler._dict_to_xml,
        },
        "dynamic_key": {"item": "items"},
        "run_contexts": ["startup", "runtime"],
    },
    "skinsettings": {
        "module": skinsettingsBuilder,
        "file_type": "json",
        "file_path": SKINSETTINGS,
        "handler": JSONHandler,
        "write_kwargs": {},
        "dynamic_key": {},
        # "run_contexts": ["buildtime"],
        "run_contexts": ["startup"],
    },
    "variables": {
        "module": variablesBuilder,
        "file_type": "xml",
        "file_path": VARIABLES,
        "handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "variable",
            "sub_element_name": "value",
            "transform_func": XMLHandler._dict_to_xml,
        },
        "dynamic_key": {"index": "index"},
        # "run_contexts": ["buildtime"],
        "run_contexts": ["startup"],
    },
}
