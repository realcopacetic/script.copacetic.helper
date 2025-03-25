# author: realcopacetic

import xbmcgui

from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    execute,
    infolabel,
    log,
    skin_string,
    window_property,
)

CONTENT_TYPES = {
    "movies": 10,
    "sets": 11,
    "tvshows": 12,
    "seasons": 13,
    "episodes": 14,
    "artists": 15,
    "albums": 16,
    "songs": 17,
    "favourites": 18,
    "addons": 19,
    "images": 20,
    "musicvideos": 21,
    "videos": 22,
}


class ViewSettings(xbmcgui.WindowXMLDialog):
    def onInit(self):
        ...
        """
        Slider group ids start from 300, e.g.
        Slider group 1: group_id = 300 button_id = 3001, slider_id = 3002)
        Slider group 2: group_id = 301 button_id = 3011, slider_id = 3012)
        window_property("viewsettings", value="true")
        self.last_focus_id = None
        self.current_content = next(iter(CONTENT_TYPES))

        # Parse both JSON files
        self.expressions_json = JSONHandler(EXPRESSIONS_MAP)
        if not self.expressions_json.file_exists():
            log(f"Expressions map file not found: {EXPRESSIONS_MAP}", force=True)
        self.expressions_map = self.expressions_json.parse()

        self.skinstrings_json = JSONHandler(SKIN_STRINGS_MAP)
        if not self.skinstrings_json.file_exists():
            log(f"Skin strings map file not found: {SKIN_STRINGS_MAP}", force=True)
            return
        self.skinstrings_map = self.skinstrings_json.parse()

        # Create sliders (x00) and their corresponding buttons (x01)
        categories = list(self.expressions_map.keys())
        self.group_ids = {cat: 300 + i for i, cat in enumerate(categories)}

        self.sliders = {}
        self.slider_buttons = {}
        for cat, group_id in self.group_ids.items():
            button_id = int(f"{group_id}1")
            slider_id = int(f"{group_id}2")
            slider_ctrl = self.getControl(slider_id)
            button_ctrl = self.getControl(button_id)
            if slider_ctrl:
                self.sliders[cat] = slider_ctrl
            else:
                log(
                    f"Slider control for category {cat} (ID {slider_id}) not found",
                    force=True,
                )
            if button_ctrl:
                self.slider_buttons[cat] = button_ctrl
            else:
                log(
                    f"Button control for category {cat} (ID {button_id}) not found",
                    force=True,
                )
        for cat in self.group_ids.keys():
            self.slider_update(cat, self.current_content)
        self.check_dependencies()
        """

    def slider_update(self, category: str, content_type: str) -> None:
        ...
        """
        Updates slider position.
        Sets this value to the corresponding button.
        
        key = f"{category}_{content_type}"
        options = self.skinstrings_map.get(key, [])
        current_value = infolabel(f"Skin.String({key})") or options[0]
        try:
            current_index = options.index(current_value) + 1
        except ValueError:
            current_index = 1

        # Update slider
        slider = self.sliders.get(category)
        if slider:
            slider.setInt(current_index, 1, 1, len(options))
            log(
                f"Slider {key} set to index {current_index} (value: {current_value})",
                force=True,
            )
        else:
            log(f"No slider found for category {category}", force=True)

        # Update slider button
        button = self.slider_buttons.get(category)
        if button:
            button.setLabel(
                label=category[:-1].title(),
                label2=current_value.title(),
            )
            log(
                f"Button for {category} updated: label2 set to {current_value}",
                force=True,
            )
        else:
            log(f"No button found for category {category}", force=True)"
        """

    def check_dependencies(self) -> None:
        ...
        """
        for cat, cat_data in self.expressions_map.items():
            dependency = cat_data.get("dependency")
            if dependency:
                # For each dependency, assume dependency is a dict like {"views": ["grid"]}
                for dep_cat, allowed_values in dependency.items():
                    dep_key = f"{dep_cat}_{self.current_content}"
                    current_value = infolabel(f"Skin.String({dep_key})")
                    group_id = self.group_ids.get(cat)
                    if current_value in allowed_values:
                        execute(f"Control.SetVisible({group_id})")
                    else:
                        execute(f"Control.SetHidden({group_id})")
                        log(
                            f"Hiding category {cat} because dependency not met (expected {allowed_values}, got {current_value})",
                            force=True,
                        )
                        """

    def onAction(self, action):
        ...
        """
        current_focus = self.getFocusId()
        if current_focus != self.last_focus_id:
            self.onFocusChanged(current_focus)
            self.last_focus_id = current_focus

        a_id = action.getId()

        # Handle actions for slider button controls
        for category, button in self.slider_buttons.items():
            if current_focus == button.getId():
                if a_id == xbmcgui.ACTION_SELECT_ITEM:
                    slider = self.sliders.get(category)
                    self.setFocusId(slider.getId())

        # Handle actions for slider controls
        for category, slider in self.sliders.items():
            if current_focus == slider.getId():
                if a_id == xbmcgui.ACTION_SELECT_ITEM:
                    button = self.slider_buttons.get(category)
                    self.setFocusId(button.getId())
                elif a_id in (xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT):
                    new_index = slider.getInt()  # 1-indexed slider value.
                    slider_key = f"{category}_{self.current_content}"
                    try:
                        new_value = self.skinstrings_map[slider_key][new_index - 1]
                    except (IndexError, KeyError):
                        new_value = self.skinstrings_map[slider_key][0]
                    skin_string(slider_key, value=new_value)
                    button = self.slider_buttons.get(category)
                    button.setLabel(label2=new_value.title())
                    self.check_dependencies()

        # Pass any unhandled actions to the parent class.
        super().onAction(action)
        """

    def onFocusChanged(self, current_focus):
        ...
        """
        if current_focus < 100:
            content_type = next(
                (key for key, cid in CONTENT_TYPES.items() if cid == current_focus),
                None,
            )
            if content_type:
                self.current_content = content_type
                for category in self.sliders.keys():
                    self.slider_update(category, content_type)
            self.check_dependencies()"""
