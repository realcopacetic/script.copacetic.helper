# author: realcopacetic

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import xbmcgui

from resources.lib.shared import logger as log
from resources.lib.windows.controls import (
    BaseControlHandler,
    ButtonHandler,
    CycleHandler,
    EditHandler,
    RadioButtonHandler,
    SliderExHandler,
    SliderHandler,
)

if TYPE_CHECKING:
    from resources.lib.builders.runtime import RuntimeStateManager

CONTROL_REGISTRY = {
    "button": (ButtonHandler, (xbmcgui.ControlButton,)),
    "cycle": (CycleHandler, (xbmcgui.ControlButton,)),  # cycle is a button variant
    "edit": (EditHandler, (xbmcgui.ControlEdit,)),
    "radiobutton": (RadioButtonHandler, (xbmcgui.ControlRadioButton,)),
    "slider": (SliderHandler, (xbmcgui.ControlSlider,)),
    "sliderex": (SliderExHandler, (xbmcgui.ControlSlider, xbmcgui.ControlButton)),
}


class DynamicControlFactory:
    """
    Builds dynamic control handlers from JSON definitions, validating that
    each XML control matches the declared type before construction.
    """

    @staticmethod
    def create_handler(
        control: dict,
        get_control_func: Callable[[int], xbmcgui.Control],
        runtime_manager: RuntimeStateManager,
    ) -> BaseControlHandler | None:
        """
        Build a handler for one control. Returns None if the control_type is
        unknown, any required XML control is missing, or any fetched instance
        is the wrong xbmcgui type. Mismatched or partially-fetched controls
        are hidden and disabled so dead slots don't trap focus.

        :param control: Control definition dict from JSON.
        :param get_control_func: Window's getControl method for fetching by id.
        :param runtime_manager: Runtime state manager passed to the handler.
        :return: Handler instance, or None if creation failed.
        """
        control_type = control.get("control_type")
        entry = CONTROL_REGISTRY.get(control_type)
        if not entry:
            return None

        handler_cls, expected_types = entry
        ids = [control["id"]]
        if control_type == "sliderex":
            ids.append(int(f"{control['id']}0"))

        instances: list[xbmcgui.Control] = []
        try:
            for i in ids:
                instances.append(get_control_func(i))
        except RuntimeError as e:
            log.warning(
                f"DynamicControlFactory → control id {control['id']} "
                f"({control_type}) skipped — missing in XML: {e}"
            )
            for inst in instances:
                inst.setVisible(False)
            return None

        for inst, expected in zip(instances, expected_types):
            if not isinstance(inst, expected):
                log.warning(
                    f"DynamicControlFactory → control id {control['id']} "
                    f"({control_type}) expected {expected.__name__} but XML "
                    f"returned {type(inst).__name__}; skipping handler."
                )
                for i in instances:
                    i.setVisible(False)
                return None

        return handler_cls(control, *instances, runtime_manager=runtime_manager)
