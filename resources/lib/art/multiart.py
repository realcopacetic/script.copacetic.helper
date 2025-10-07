# author: realcopacetic

from resources.lib.shared.utilities import to_int, clamp
from resources.lib.plugin.helpers import get_infolabels

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
