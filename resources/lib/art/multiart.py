# author: realcopacetic

import random
from typing import Iterable, Mapping, Any

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.helpers import get_infolabels
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import clamp, to_int, infolabel
from resources.lib.apis.tmdb.cache import TmdbCache

DEFAULT_SLOTS = 15
MAX_SLOTS = 50

_TMDB_CACHE = TmdbCache()


def build_multiart_dict(
    *,
    target: str,
    multiart_type: str | None,
    max_items: int | str | None,
    get_extra_multiart: bool,
    dbtype: str | None,
    language: str,
) -> dict[str, str]:
    """
    Build a combined multiart dict from local artwork and optional TMDb artwork.

    This function abstracts EVERYTHING needed:
    - determine local multiart sequence
    - fetch TMDb art if requested
    - merge sequences
    - return normalized {multiart, multiart1..N}
    """
    if not multiart_type:
        return {}

    local_seq = multiart_sequence_from_infolabels(
        target=target,
        art_type=multiart_type,
        max_items=max_items,
    )

    tmdb_art = _get_tmdb_art(
        target=target,
        dbtype=dbtype,
        language=language,
        get_extra_multiart=get_extra_multiart,
    )

    tmdb_seq: list[str] = []
    if tmdb_art:
        tmdb_seq = multiart_sequence_from_dict(
            art=tmdb_art,
            art_type=multiart_type,
            max_items=max_items,
        )

    merged = merge_multiart_sequences(primary=local_seq, secondary=tmdb_seq)
    return sequence_to_multiart_dict(merged)


def _get_tmdb_art(
    *,
    target: str,
    dbtype: str | None,
    language: str,
    get_extra_multiart: bool,
) -> dict[str, str]:
    """
    Internal helper: return TMDb 'art' dict for the current ListItem.
    """
    if not get_extra_multiart:
        return {}

    tmdb_id = to_int(infolabel(f"{target}.UniqueID(tmdb)"))
    if tmdb_id <= 0:
        return {}

    resolved_dbtype = infolabel(f"{target}.DBType") or dbtype
    if not resolved_dbtype:
        return {}

    try:
        art = _TMDB_CACHE.get_field(resolved_dbtype, tmdb_id, language, "art") or {}
        return art
    except Exception as exc:  # noqa: BLE001
        log.debug(
            f"_get_tmdb_art → TMDb lookup failed for type={resolved_dbtype}, "
            f"tmdb_id={tmdb_id}: {exc!r}"
        )
        return {}


def multiart_sequence_from_infolabels(
    target: str,
    art_type: str | None,
    max_items: int | str | None = None,
) -> list[str]:
    """
    Build an ordered list of multiart URLs from Kodi infolabels.

    :param target: Infolabel prefix (e.g. "ListItem" or "Container(3100).ListItem").
    :param art_type: Base art key such as "fanart" or "poster".
    :param max_items: Maximum number of slots to read, defaults to DEFAULT_SLOTS.
    :return: List of artwork URLs in multiart order.
    """
    if not art_type:
        return []

    limit = int(clamp(to_int(max_items, DEFAULT_SLOTS), 0, MAX_SLOTS))
    art_keys = [f"Art({art_type})"] + [
        f"Art({art_type}{i})" for i in range(1, limit + 1)
    ]

    labels = get_infolabels(target, art_keys)
    return [labels[k] for k in art_keys if labels.get(k)]


def multiart_sequence_from_dict(
    art: Mapping[str, str],
    art_type: str | None,
    max_items: int | str | None = None,
) -> list[str]:
    """
    Build an ordered list of multiart URLs from a plain art dict.

    :param art: Artwork mapping using keys like "fanart", "fanart1", "fanart2".
    :param art_type: Base art key such as "fanart" or "poster".
    :param max_items: Maximum number of slots to read, defaults to DEFAULT_SLOTS.
    :return: List of artwork URLs in multiart order.
    """
    if not art_type:
        return []

    limit = int(clamp(to_int(max_items, DEFAULT_SLOTS), 0, MAX_SLOTS))

    base = art.get(art_type)
    extras = [url for i in range(1, limit + 1) if (url := art.get(f"{art_type}{i}"))]

    return [base, *extras] if base else extras


def merge_multiart_sequences(
    primary: Iterable[str],
    secondary: Iterable[str],
) -> list[str]:
    """
    Build an ordered list of multiart URLs from a plain art dict.

    :param art: Artwork mapping using keys like "fanart", "fanart1", "fanart2".
    :param art_type: Base art key such as "fanart" or "poster".
    :param max_items: Maximum number of slots to read, defaults to DEFAULT_SLOTS.
    :return: List of artwork URLs in multiart order.
    """
    merged: list[str] = []
    seen: set[str] = set()

    for url in (*primary, *secondary):
        if url and url not in seen:
            merged.append(url)
            seen.add(url)

    return merged


def sequence_to_multiart_dict(urls: Iterable[str]) -> dict[str, str]:
    """
    Turn a list of URLs into the standard multiart dict:

        urls[0] → "multiart"
        urls[1] → "multiart1"
        urls[2] → "multiart2"
        ...
    """
    seq = [u for u in urls if u]
    if not seq:
        return {}

    result: dict[str, str] = {"multiart": seq[0]}
    for index, url in enumerate(seq[1:], start=1):
        result[f"multiart{index}"] = url

    return result


def set_multiart_fadelabel(
    fadelabel_id: int | str,
    art: dict[str, str],
    *,
    randomize: bool = True,
    keep_main_first: bool = True,
) -> bool:
    """
    Seed a FadeLabel control with a multiart sequence.

    :param fadelabel_id: Control id of the FadeLabel to populate.
    :param art: Dict containing "multiart" and "multiart1..N".
    :param randomize: Shuffle extras if True.
    :param keep_main_first: Keep the first image first (recommended ON).
    :return: True if labels were set successfully.
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
        return False

    return True
