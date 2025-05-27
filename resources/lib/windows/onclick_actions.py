# author: realcopacetic

from xbmcgui import Dialog
from resources.lib.shared.utilities import execute


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
        return dlg.browse(
            cfg.get("browseType", "files"),
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
        return dlg.browseSingle(
            cfg.get("browseType", "files"),
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
        return dlg.browseMultiple(
            cfg.get("browseType", "files"),
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
            cfg["items"],
            cfg.get("autoclose"),
            cfg.get("preselect"),
            cfg.get("useDetails"),
        )
