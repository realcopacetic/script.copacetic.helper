# author: realcopacetic

import xbmcgui

from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    CONTROLS,
    SKINSETTINGS,
    log,
)
from resources.lib.windows.control_factory import DynamicControlFactory


class DynamicEditor(xbmcgui.WindowXMLDialog):
    def __init__(self, xmlFilename, skinPath, defaultSkin, defaultRes):
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
            handler.update_visibility(self.current_content)

    def onAction(self, action):
        a_id = action.getId()
        current_focus = self.getFocusId()

        if current_focus != self.last_focus:
            self.onFocusChanged(current_focus)
            self.last_focus = current_focus

        for handler in self.handlers.values():
            handler.handle_interaction(self.current_content, a_id, current_focus)

        for handler in self.handlers.values():  
            handler.update_visibility(self.current_content)

        super().onAction(action)

    def onFocusChanged(self, focus_id):
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
