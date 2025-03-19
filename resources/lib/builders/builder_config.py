# author: realcopacetic

from resources.lib.builders.modules import (
    controlsBuilder,
    expressionsBuilder,
    skinsettingsBuilder,
)
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.xml import XMLHandler
from resources.lib.shared.utilities import EXPRESSIONS, SKINSETTINGS

BUILDER_CONFIG = {
    "expressions": {
        "module": expressionsBuilder,
        "run_at_startup": True,
        "file_type": "xml",
        "file_path": EXPRESSIONS,
        "handler": XMLHandler,
        "write_kwargs": {
            "root_tag": "includes",
            "element_name": "expression",
            "transform_func": XMLHandler._dict_to_xml,  # Explicitly define transform function
        },
    },
    "skinsettings": {
        "module": skinsettingsBuilder,
        "run_at_startup": True,
        "file_type": "json",
        "file_path": SKINSETTINGS,
        "handler": JSONHandler,
        "write_kwargs": {},
    },
    "controls": {
        "module": controlsBuilder,
        "run_at_startup": False,
        "file_type": None,
        "file_path": None,
        "handler": None,
        "write_kwargs": {},
    },
}
