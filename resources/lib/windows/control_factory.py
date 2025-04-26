# author: realcopacetic

from resources.lib.shared.utilities import log
from resources.lib.windows.controls import (
    ButtonHandler,
    RadioButtonHandler,
    SliderExHandler,
    SliderHandler,
)

HANDLER_REGISTRY = {
    "button": ButtonHandler,
    "radiobutton": RadioButtonHandler,
    "slider": SliderHandler,
    "sliderex": SliderExHandler,
    # add more control types here
}


class DynamicControlFactory:
    @staticmethod
    def create_handler(control, get_control_func, skinsettings):
        control_type = control.get("control_type")

        if control_type == "sliderex":
            try:
                slider_instance = get_control_func(control["id"])
                button_id = int(f"{control['id']}0")
                button_instance = get_control_func(button_id)
                return SliderExHandler(
                    control, slider_instance, button_instance, skinsettings
                )
            except RuntimeError as e:
                log(
                    f"SliderExHandler skipped: missing slider ({control['id']}) or button ({button_id})"
                )
                return None

        handler_cls = HANDLER_REGISTRY.get(control_type)
        if handler_cls:
            instance = get_control_func(control["id"])
            return handler_cls(control, instance, skinsettings)

        return None
