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
        "expand_name": True,
        "expand_fields": ["label", "visible", "update_trigger", "dynamic_setting"],
        "special_placeholders": {"id": "id_start"},
        "support_fallback": False,
        "run_contexts": ["run_time"],
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
        "expand_name": True,
        "expand_fields": ["rules[*].condition", "rules[*].value"],
        "special_placeholders": {"item": "items"},
        "support_fallback": True,
        "run_contexts": ["startup_time", "run_time"],
    },
    "skinsettings": {
        "module": skinsettingsBuilder,
        "file_type": "json",
        "file_path": SKINSETTINGS,
        "handler": JSONHandler,
        "write_kwargs": {},
        "expand_name": True,
        "expand_fields": ["rules[*].condition", "rules[*].value"],
        "special_placeholders": {},
        "support_fallback": False,
        "run_contexts": ["build_time"],
    },
    "variables": {
        "module": variablesBuilder,
        "file_type": "xml",
        "file_path": VARIABLES,
        "handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "variable",
            "transform_func": XMLHandler._dict_to_xml,
        },
        "expand_name": True,
        "expand_fields": ["values[*].condition", "values[*].value"],
        "special_placeholders": {"index": "index"},
        "support_fallback": False,
        "run_contexts": ["build_time"],
    },
}
