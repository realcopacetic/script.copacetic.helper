# author: realcopacetic

import random

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.helpers import get_infolabels
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import clamp, to_int

DEFAULT_SLOTS = 15
MAX_SLOTS = 50


def collect_multiart(
    target: str, art_type: str | None, max_items: int | str | None = None
) -> dict[str, str]:
    """
    Build a standardized multiart map for one Art() type; base → "multiart", extras → "multiart1..N".
    Missing slots are skipped; positions are not compacted.

    :param target: Infolabel prefix (e.g., "ListItem" or "Container(3100).ListItem").
    :param art_type: Art() key (e.g., "fanart", "poster", "tvshow.poster").
    :param max_items: Maximum number of multiart slots: default 15, cap 50
    :return: {"multiart": "...", "multiart1": "...", ...} for existing slots only.
    """
    if not art_type:
        return {}

    limit = int(clamp(to_int(max_items, DEFAULT_SLOTS), 0, MAX_SLOTS))
    name_keys = ["multiart"] + [f"multiart{i}" for i in range(1, limit + 1)]
    art_keys = [f"Art({art_type})"] + [
        f"Art({art_type}{i})" for i in range(1, limit + 1)
    ]
    labels = get_infolabels(target, art_keys)
    return {name: labels[k] for name, k in zip(name_keys, art_keys) if labels.get(k)}


def set_multiart_fadelabel(
    fadelabel_id: int | str,
    art: dict[str, str],
    *,
    randomize: bool = True,
    keep_main_first: bool = True,
) -> bool:
    """
    Seed a FadeLabel control with a multiart sequence: main art followed by shuffled extras.

    :param fadelabel_id: Control id of the FadeLabel to populate.
    :param art: Mapping that may include "multiart" and "multiart1..N" keys with URLs.
    :param randomize: If True, shuffle extras; otherwise keep original order.
    :param keep_main_first: If True, place 'multiart' (if present) before extras.
    :return: True if labels were set successfully, else False.
    """
    try:
        win = Window(getCurrentWindowId())
        ctrl = win.getControl(to_int(fadelabel_id))
        ctrl.setVisible(True)
        ctrl.reset()
        main = art.get("multiart")
        extras = [
            v
            for k, v in art.items()
            if k.startswith("multiart") and k != "multiart" and v
        ]
        if randomize:
            random.shuffle(extras)

        ordered = ([main] if keep_main_first and main else []) + extras
        for label in filter(None, ordered):
            ctrl.addLabel(label)

    except Exception as e:
        log.warning(f"Unable to set multiart fadelabel → {e}")
