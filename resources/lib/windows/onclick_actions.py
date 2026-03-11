# author: realcopacetic

from xbmcgui import Dialog

from resources.lib.shared import logger as log

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
        browse_string = cfg.get("browseType", "directories")
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
        browse_string = cfg.get("browseType", "files")
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
        browse_string = cfg.get("browseType", "files")
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
    def browse_content(cfg):
        """
        Show a recursive content path browser using JSON-RPC directory lookups.

        Returns a dict or None if cancelled:
          widget mode: {"path": str, "label": str}
          menu mode:   {"path": str, "label": str, "type": str,
                        "window": str, "action": str}

        The caller (ButtonControlHandler.handle_interaction) extracts "path"
        for the control's own field and, if cfg["label_field"] is set, writes
        "label" to that sibling runtime field.
        """
        from resources.lib.windows.browse import browse_content

        return browse_content(cfg)

    @staticmethod
    def colorpicker(cfg):
        """
        Show a colour picker dialog and return the selected hex colour string,
        or None if cancelled.
        """
        dlg = Dialog()
        result = dlg.colorpicker(
            cfg.get("heading", ""),
            cfg.get("default", ""),
        )
        return result if result else None

    @staticmethod
    def custom(cfg):
        """
        Execute a custom Kodi built-in command.
        """
        log.execute(cfg["action"])

    @staticmethod
    def input(cfg):
        """
        Show a keyboard input dialog and return the entered string,
        or None if cancelled.
        """
        dlg = Dialog()
        result = dlg.input(
            cfg.get("heading", ""),
            cfg.get("default", ""),
            cfg.get("inputType", 0),
        )
        return result if result != "" else None

    @staticmethod
    def numeric(cfg):
        """
        Show a numeric input dialog and return the entered value as a string,
        or None if cancelled.
        """
        dlg = Dialog()
        result = dlg.numeric(
            cfg.get("numericType", 0),
            cfg.get("heading", ""),
            cfg.get("default", ""),
        )
        return result if result != "" else None

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
