# author: realcopacetic

import xbmcgui

from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    CONTROLS,
    SKINSETTINGS,
    execute,
    log,
)
from resources.lib.windows.control_factory import DynamicControlFactory


class DynamicEditor(xbmcgui.WindowXMLDialog):
    """
    A dynamic skin settings editor window that adapts controls based on focus.
    Dynamically builds and manages visibility, interaction, and values for skin settings.
    """

    def __init__(self, xmlFilename, skinPath, defaultSkin, defaultRes):
        """
        Initialize the editor and prepare handlers for dynamic/static controls.

        :param xmlFilename: Name of the active XML window file.
        :param skinPath: Path to the current skin directory.
        :param defaultSkin: Name of the default skin.
        :param defaultRes: Default resolution.
        """
        super().__init__()
        self._xml_filename = xmlFilename.lower()
        self.controls_handler = JSONHandler(CONTROLS)
        self.skinsettings_handler = JSONHandler(SKINSETTINGS)

        self.handlers = {}

        self.skinsettings = {}
        self.all_controls = {}
        self.static_controls = {}
        self.dynamic_controls = {}
        self.control_instances = {}

        self.current_content = None
        self.last_focus = None

        self.build_dicts()

    def build_dicts(self):
        """
        Populate control and skinsetting mappings from JSON definitions.
        Separates static and dynamic controls.
        """
        self.skinsettings = {
            setting_id: setting
            for settings_dict in self.skinsettings_handler.data.values()
            for setting_id, setting in settings_dict.items()
        }

        self.all_controls = {
            control_id: control
            for controls_dict in self.controls_handler.data.values()
            for control_id, control in controls_dict.items()
            if any(w in self._xml_filename for w in control.get("window", []))
        }

        for cid, ctrl in self.all_controls.items():
            if "dynamic_linking" in ctrl:
                self.dynamic_controls[cid] = ctrl
            else:
                self.static_controls[cid] = ctrl

    def onInit(self):
        """
        Initializes controls and binds handlers. Applies initial visibility logic.
        """
        for control_id, control in self.all_controls.items():
            try:
                instance = self.getControl(control["id"])
                self.control_instances[control_id] = instance
                handler = DynamicControlFactory.create_handler(
                    control, self.getControl, self.skinsettings
                )
                if handler:
                    self.handlers[control_id] = handler

            except RuntimeError as e:
                log(
                    f"Warning: Control ID {control['id']} ({control_id}) not found in XML layout: {e}"
                )

        # Trigger initial focus and visibility logic manually
        self.last_focus = self.getFocusId()
        self.onFocusChanged(self.last_focus)

        for handler in self.handlers.values():
            handler.update_visibility(self.current_content, self.last_focus)

    def onAction(self, action):
        """
        Called by Kodi when a user performs an action (e.g., movement, selection).
        Propagates action to each handler, updates focus and visibility.

        :param action: xbmcgui.Action object representing the user's input.
        """
        requested_focus_change = None
        a_id = action.getId()
        current_focus = self.getFocusId()

        for handler in self.handlers.values():
            handler.handle_interaction(self.current_content, a_id, current_focus)
            if hasattr(handler, "focus_target_id"):
                requested_focus_change = handler.focus_target_id
                del handler.focus_target_id

        if requested_focus_change:
            execute(f"Control.SetFocus({requested_focus_change})")
            current_focus = requested_focus_change

        if current_focus != self.last_focus:
            self.onFocusChanged(current_focus)
            self.last_focus = current_focus

        for handler in self.handlers.values():  
            handler.update_visibility(self.current_content, self.last_focus)

        super().onAction(action)

    def onFocusChanged(self, focus_id):
        """
        Called when the focused control changes.
        Updates the current content type and triggers updates for linked dynamic controls.

        :param focus_id: ID of the newly focused control.
        """
        focus_control_id = next(
            (
                cid
                for cid, ctrl in self.static_controls.items()
                if ctrl["id"] == focus_id
            ),
            None,
        )

        if focus_control_id:
            self.current_content = focus_control_id
            # Only update dyanmic control values when focusing a static control
            for handler in self.handlers.values():
                handler.update_value(self.current_content)
