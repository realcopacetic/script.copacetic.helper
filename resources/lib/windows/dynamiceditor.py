# author: realcopacetic

import xbmcgui
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    log,
    SKINSETTINGS,
    CONTROLS,
    skin_string,
    infolabel,
)


class DynamicEditor(xbmcgui.WindowXMLDialog):
    def __init__(self, xmlFilename, skinPath, defaultSkin, defaultRes):
        super().__init__()
        self._xml_filename = xmlFilename.lower()
        self.controls_handler = JSONHandler(CONTROLS)
        self.skinsettings_handler = JSONHandler(SKINSETTINGS)

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
                control_obj = self.getControl(control["id"])
                self.control_instances[control_id] = control_obj
            except RuntimeError as e:
                log(
                    f"Warning: Control ID {control['id']} ({control_id}) not found in XML layout: {e}"
                )

        # Trigger initial focus logic manually
        self.last_focus = self.getFocusId()
        self.onFocusChanged(self.last_focus)

    def onAction(self, action):
        a_id = action.getId()
        current_focus = self.getFocusId()

        if current_focus != self.last_focus:
            self.onFocusChanged(current_focus)
            self.last_focus = current_focus

        for control_id, control in self.dynamic_controls.items():
            instance = self.control_instances[control_id]
            if control["control_type"] == "slider":
                self.handle_slider_interactions(control, instance, a_id)
            elif control["control_type"] == "radiobutton":
                ...

        super().onAction(action)

    def handle_slider_interactions(self, control, instance, a_id):
        if a_id in (xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT):
            index = instance.getInt()
            link = self.get_active_link(control)
            if not link:
                return

            setting_id = link["linked_setting"]
            values = self.skinsettings.get(setting_id, {}).get("items", [])

            if 0 <= index < len(values):
                value = values[index]
                skin_string(setting_id, value)
                log(f"Updated setting: {setting_id} → {value}")

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

        for control_id, control in self.dynamic_controls.items():
            instance = self.control_instances.get(control_id)
            link = self.get_active_link(control)
            if link:
                self.update_dynamic_control_value(
                    control, instance, link["linked_setting"]
                )

    def update_dynamic_control_value(self, control, instance, linked_setting):
        setting_values = self.skinsettings.get(linked_setting, {}).get("items", [])
        if not setting_values:
            return

        if control["control_type"] == "slider":
            index = self.get_slider_index(linked_setting, setting_values)
            instance.setInt(index, 0, 1, len(setting_values) - 1)

        elif control["control_type"] == "radiobutton":
            ...

    def get_slider_index(self, setting_id, setting_values):
        current_value = infolabel(f"Skin.String({setting_id})")
        try:
            return setting_values.index(current_value)
        except ValueError:
            return 0

    def evaluate_trigger(self, trigger):
        if trigger.startswith("focused(") and trigger.endswith(")"):
            name = trigger[8:-1]
            return self.current_content == name
        return False

    def get_active_link(self, control):
        return next(
            (
                link
                for link in control.get("dynamic_linking", [])
                if self.evaluate_trigger(link.get("update_trigger", ""))
            ),
            None,
        )
