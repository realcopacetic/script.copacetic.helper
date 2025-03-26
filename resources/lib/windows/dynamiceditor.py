# author: realcopacetic

import xbmcgui
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import log, SKINSETTINGS, CONTROLS


class DynamicEditor(xbmcgui.WindowXMLDialog):
    def __init__(self, xmlFilename, skinPath, defaultSkin, defaultRes):
        super().__init__()
        self._xml_filename = xmlFilename.lower()
        self.controls_handler = JSONHandler(CONTROLS)
        self.skinsettings_handler = JSONHandler(SKINSETTINGS)

        self.parent_controls = {}
        self.child_controls = {}

    def onInit(self):
        self.build_controls()

        self.parent_control_instances = {}
        self.child_control_instances = {}

        self.current_content = next(iter(self.parent_controls)).replace("_button", "")

        self.all_skinsettings = {
            setting_id: setting
            for settings_dict in self.skinsettings_handler.data.values()
            for setting_id, setting in settings_dict.items()
        }

        for control_id, control in self.parent_controls.items():
            control_obj = self.getControl(control["id"])
            if control_obj:
                self.parent_control_instances[control_id] = control_obj

        for control_id, control in self.child_controls.items():
            control_obj = self.getControl(control["id"])
            if control_obj:
                self.child_control_instances[control_id] = control_obj

        self.update_child_controls()

    def build_controls(self):

        all_controls = {
            control_id: control
            for controls_dict in self.controls_handler.data.values()
            for control_id, control in controls_dict.items()
            if any(w in self._xml_filename for w in control.get("window", []))
        }

        self.parent_controls = {
            control_id: control
            for control_id, control in all_controls.items()
            if control.get("role") == "parent"
        }

        self.child_controls = {
            control_id: control
            for control_id, control in all_controls.items()
            if control.get("role") == "child"
        }
