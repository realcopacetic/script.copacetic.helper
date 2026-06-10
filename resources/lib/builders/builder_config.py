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
            "transform_func": sort_outer_keys(XMLHandler._simple_dict_to_xml),
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

# Read-side resolver inputs — resolved on demand, never written as builders.
MAPPINGS_FOLDER = "mappings"
CONFIGS_FOLDER = "configs"
CONTROLS_FOLDER = "controls"
RESOLVER_SUBFOLDERS = (MAPPINGS_FOLDER, CONFIGS_FOLDER, CONTROLS_FOLDER)

# Every template input folder a skin may provide: resolver inputs plus the
# write-side builders, whose keys are their folder names. Deriving the builder
# half from BUILDER_CONFIG keeps the opt-in signal in sync when a builder is added.
TEMPLATE_SUBFOLDERS = (*RESOLVER_SUBFOLDERS, *BUILDER_CONFIG)
