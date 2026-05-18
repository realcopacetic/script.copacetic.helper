# author: realcopacetic

import xbmc
from xbmcgui import Dialog

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import condition, infolabel, skin_string

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
        Widget mode returns ``{path, label, icon, target}``; menu mode
        also adds ``{type, window, action}`` for menu-item construction.

        :param cfg: Onclick config dict (supports ``mode``: "widget" or "menu").
        :return: Result dict, or None if cancelled.
        """
        from resources.lib.windows.browse import browse_content

        return browse_content(cfg)

    @staticmethod
    def browse_image(cfg):
        """
        Show Kodi's image browser dialog opened at a configured folder,
        using a transient skin string and a non-existent sentinel
        filename for unambiguous cancel detection.

        :param cfg: Dict with ``folder`` (str) — starting path for the browser.
        :return: Selected path as a string, or None if cancelled.
        """

        SCRATCHPAD = "_copacetic_image_picker"

        folder = cfg.get("folder", "")
        if not folder:
            log.warning("browse_image: 'folder' param missing; aborting")
            return None
        if not folder.endswith("/"):
            folder += "/"

        # Seed the scratchpad; one-arg Skin.SetImage uses the current string
        # value as its starting hint.
        skin_string(SCRATCHPAD, folder)
        log.execute(f"Skin.SetImage({SCRATCHPAD})")

        monitor = xbmc.Monitor()

        # Wait for the dialog to open (bounded against silent failure).
        waited = 0
        while not condition("Window.IsActive(FileBrowser)") and waited < 60:
            if monitor.waitForAbort(0.05):
                return None
            waited += 1
        if waited >= 60:
            log.warning("browse_image: file browser did not open within 3s")
            skin_string(SCRATCHPAD)
            return None

        # Wait for the dialog to close.
        while condition("Window.IsActive(FileBrowser)"):
            if monitor.waitForAbort(0.05):
                return None

        # Poll for writeback — Kodi commits the new value shortly after the
        # dialog closes, not synchronously with it. Bounded to ~1s.
        # Loop exits early as soon as the value differs from the seed.
        result = ""
        waited = 0
        while waited < 20:
            result = infolabel(f"Skin.String({SCRATCHPAD})")
            if result and result != folder:
                break
            if monitor.waitForAbort(0.05):
                return None
            waited += 1

        skin_string(SCRATCHPAD)  # clear

        return None if (not result or result == folder) else result

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
