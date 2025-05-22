# author: realcopacetic

from pathlib import Path

import xbmcgui

from resources.lib.builders.builder_config import BUILDER_MAPPINGS
from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import (
    CONFIGS,
    CONTROLS,
    RUNTIME_STATE,
    SKINEXTRAS,
    execute,
    infolabel,
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
        self.configs_handler = JSONHandler(CONFIGS)

        self.mapping_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=["custom_mappings"],
            grouping_key=None,
        )
        self.all_mappings = {
            **BUILDER_MAPPINGS,
            **dict(self.mapping_merger.cached_merged_data),
        }
        self.runtime_manager = RuntimeStateManager(
            mappings=self.all_mappings,
            configs_path=CONFIGS,
            runtime_state_path=RUNTIME_STATE,
        )

        self.handlers = {}
        self.control_instances = {}
        self.current_listitem = None
        self.container_position = -1

        self.build_dicts()

    def build_dicts(self):
        """
        Populate control and skinsetting mappings from JSON definitions.
        Separates static and dynamic controls.
        """
        self.configs = {
            setting_id: setting
            for settings_dict in self.configs_handler.data.values()
            for setting_id, setting in settings_dict.items()
        }

        filtered_controls = {
            control_id: control
            for controls_dict in self.controls_handler.data.values()
            for control_id, control in controls_dict.items()
            if any(w in self._xml_filename for w in control.get("window", []))
        }

        self.listitems = {}
        self.dynamic_controls = {}

        for cid, ctrl in filtered_controls.items():
            if ctrl.get("control_type") == "listitem":
                self.listitems[cid] = ctrl
            elif "dynamic_linking" in ctrl:
                self.dynamic_controls[cid] = ctrl

    def onInit(self):
        """
        Initializes controls and binds handlers. Applies initial visibility logic.
        """
        self.list_container = self.getControl(100)
        self.description_label = self.getControl(6)

        for cid, item in self.listitems.items():
            raw = item.get("label", "")
            label = infolabel(raw) if raw.startswith("$") else raw

            listitem = xbmcgui.ListItem(label=label)
            listitem.setProperty("content_id", cid)
            icon = item.get("icon")

            listitem.setArt({item.get("icon", "DefaultCopacetic.png"): icon})
            self.list_container.addItem(listitem)

        current_focus = self.list_container.getId()
        execute(f"SetFocus({current_focus})")

        for control_id, control in self.dynamic_controls.items():
            try:
                instance = self.getControl(control["id"])
                self.control_instances[control_id] = instance
                handler = DynamicControlFactory.create_handler(
                    control,
                    self.getControl,
                    self.configs,
                    self.runtime_manager,
                )
                if handler:
                    self.handlers[control_id] = handler
            except RuntimeError as e:
                log(
                    f"Warning: Control ID {control['id']} ({control_id}) not found in XML layout: {e}"
                )

        if self.listitems:
            self.list_container.selectItem(0)
            self.onListScroll(current_focus)

    def onAction(self, action):
        """
        Called by Kodi when a user performs an action (e.g., movement, selection).
        Propagates action to each handler, updates focus and visibility.

        :param action: xbmcgui.Action object representing the user's input.
        """
        a_id = action.getId()
        current_focus = self.getFocusId()
        requested_focus_change = None

        if current_focus == self.list_container.getId():
            self.onListScroll(current_focus)
        else:
            for handler in self.handlers.values():
                handler.handle_interaction(
                    self.current_listitem,
                    self.container_position,
                    self.getFocusId(),
                    a_id,
                )
                if hasattr(handler, "focus_target_id"):
                    requested_focus_change = handler.focus_target_id
                    del handler.focus_target_id

            if requested_focus_change:
                execute(f"Control.SetFocus({requested_focus_change})")
                current_focus = requested_focus_change

            for handler in self.handlers.values():
                handler.update_visibility(
                    self.current_listitem,
                    self.container_position,
                    current_focus,
                )

        super().onAction(action)

    def onListScroll(self, current_focus):
        """
        Update dynamic controls when the list selection changes.
        
        :param current_focus: ID of the currently focused control.
        """
        index = self.list_container.getSelectedPosition()
        if index < 0 or index == self.container_position:
            return

        self.container_position = index
        selected_item = self.list_container.getListItem(index)
        content_id = selected_item.getProperty("content_id")
        self.current_listitem = content_id

        for handler in self.handlers.values():
            handler.update_value(self.current_listitem, self.container_position)
            handler.update_visibility(
                self.current_listitem,
                self.container_position,
                current_focus,
            )

        description = self.listitems.get(content_id, {}).get("description", "")
        self.description_label.setText(description or "")
