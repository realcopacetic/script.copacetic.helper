# author: realcopacetic

from xbmcgui import Dialog
from resources.lib.shared.utilities import execute

BROWSE_TYPE_MAP = {
    "directories": 0,
    "files": 1,
    "images": 2,
    "writeable": 3,
}


class OnClickActions:
    """
    Encapsulates dialog and custom actions for button clicks.
    """

    @staticmethod
    def browse(cfg):
        """
        Show a browse dialog and return the selected path.
        """
        dlg = Dialog()
        browse_string = cfg.get("browseType", "directories"),
        browse_type = BROWSE_TYPE_MAP.get(browse_string.lower(), 0)
        return dlg.browse(
            browse_type,
            cfg["heading"],
            cfg["shares"],
            cfg.get("mask", ""),
            cfg.get("useThumbs", False),
            cfg.get("treatAsFolder", False),
            cfg.get("default", ""),
            cfg.get("enableMultiple", False),
        )

    @staticmethod
    def browse_single(cfg):
        """
        Show a single-select browse dialog and return the chosen path.
        """
        dlg = Dialog()
        browse_string = (cfg.get("browseType", "files"),)
        browse_type = BROWSE_TYPE_MAP.get(browse_string.lower(), 1)
        return dlg.browseSingle(
            browse_type,
            cfg["heading"],
            cfg["shares"],
            cfg.get("mask", ""),
            cfg.get("useThumbs", False),
            cfg.get("treatAsFolder", False),
            cfg.get("default", ""),
        )

    @staticmethod
    def browse_multiple(cfg):
        """
        Show a multi-select browse dialog and return chosen paths.
        """
        dlg = Dialog()
        browse_string = (cfg.get("browseType", "files"),)
        browse_type = BROWSE_TYPE_MAP.get(browse_string.lower(), 1)
        return dlg.browseMultiple(
            browse_type,
            cfg["heading"],
            cfg["shares"],
            cfg.get("mask", ""),
            cfg.get("useThumbs", False),
            cfg.get("treatAsFolder", False),
            cfg.get("default", ""),
        )

    @staticmethod
    def custom(cfg):
        """
        Execute a custom Kodi built-in command.
        """
        execute(cfg["action"])

    @staticmethod
    def select(cfg):
        """
        Show a selection dialog and return the chosen index.
        """
        dlg = Dialog()
        return dlg.select(
            cfg["heading"],
            cfg["display_items"],
            cfg.get("autoclose", -1),
            cfg.get("preselect", 0),
            cfg.get("useDetails", False),
        )
