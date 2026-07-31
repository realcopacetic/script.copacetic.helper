# author: realcopacetic

import random
from typing import Callable, Iterable, Mapping

from xbmc import Monitor
from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.helpers import get_infolabels
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    clamp,
    clear_label,
    infolabel,
    to_int,
    window_property,
)
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
    language: str,
) -> dict[str, str]:
    """
    Build a combined multiart dictionary from local artwork and optional TMDb artwork.

    :param target: Infolabel prefix such as "ListItem" or "Container(3100).ListItem".
    :param multiart_type: Base art type (e.g. "fanart", "poster", "keyart").
    :param max_items: Maximum number of multiart slots to read.
    :param get_extra_multiart: Whether to augment local artwork with TMDb artwork.
    :param language: TMDb language code (e.g. "en-US") used for cache lookup.
    :return: A dict mapping "multiart" and "multiartN" keys to artwork URLs.
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
    language: str,
    get_extra_multiart: bool,
) -> dict[str, str]:
    """
    Internal helper to return the TMDb 'art' mapping for the current ListItem.

    :param target: Infolabel prefix used to resolve UniqueID(tmdb) and DBType.
    :param language: TMDb language code (e.g. "en-US") used for cache lookup.
    :param get_extra_multiart: Whether TMDb artwork should be fetched.
    :return: A dict containing TMDb artwork fields, or {} if unavailable.
    """
    if not get_extra_multiart:
        return {}

    tmdb_id = to_int(infolabel(f"{target}.UniqueID(tmdb)"))
    if tmdb_id <= 0:
        return {}

    resolved_dbtype = infolabel(f"{target}.DBType")
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
    Merge two multiart sequences, preserving order and deduplicating by URL.

    :param primary: Preferred sequence of artwork URLs.
    :param secondary: Fallback sequence; duplicates of primary are dropped.
    :return: Deduplicated list with primary URLs first.
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


def order_multiart(
    art: dict[str, str],
    *,
    randomize: bool = True,
    keep_main_first: bool = True,
) -> list[str]:
    """
    Resolve the display order for a multiart dict.

    :param art: Dict containing "multiart" and "multiart1..N".
    :param randomize: Shuffle the non-main entries if True.
    :param keep_main_first: Keep the main image first (recommended ON).
    :return: Ordered list of URLs, main first.
    """
    main = art.get("multiart")
    extras = [
        v for k, v in art.items() if k.startswith("multiart") and k != "multiart" and v
    ]
    if randomize:
        random.shuffle(extras)
    return [u for u in ([main] if keep_main_first and main else []) + extras if u]


def set_multiart_fadelabel(
    fadelabel_id: int | str,
    ordered: list[str],
    *,
    alive: Callable[[], bool] | None = None,
    preserve_frozen: bool = True,
) -> bool:
    """
    Seed a FadeLabel control with a multiart sequence.

    :param fadelabel_id: Control id of the FadeLabel to populate.
    :param ordered: URLs in display order (see order_multiart).
    :param alive: Focus guard; seeding aborts if it returns False after the park.
    :param preserve_frozen: Park the displayed frame in multiart_frozen; pass
        False on cross-container serves, where that frame belongs to the
        previous region and parking it contaminates the scroll fallback.
    :return: True if labels were set successfully.
    """
    try:
        win = Window(getCurrentWindowId())
        ctrl = win.getControl(to_int(fadelabel_id))
        if preserve_frozen and (
            displayed := infolabel(f"Control.GetLabel({fadelabel_id})")
        ):
            window_property(f"multiart_frozen_{fadelabel_id}", displayed)
        elif not preserve_frozen:
            window_property(f"multiart_frozen_{fadelabel_id}")
        ctrl.setVisible(True)
        ctrl.reset()
        # Kodi keeps a FadeLabel's rotation index across reset(); it only
        # clamps to 0 when a render pass sees index >= label count. Park a
        # single empty label for ~2 frames so the clamp happens. Empirical:
        # GetLabel can't confirm the render pass, so this is a timed wait —
        # bump the interval if index-walking ever recurs under load.
        ctrl.addLabel("")
        if Monitor().waitForAbort(0.05):
            return False
        if alive and not alive():
            return False
        ctrl.reset()

        for label in filter(None, ordered):
            ctrl.addLabel(label)

    except Exception as e:
        log.warning(f"Unable to set multiart fadelabel → {e}")
        return False

    return True

def seed_multiart(
    *,
    fadelabel_id: str | None,
    multiart_dict: dict[str, str],
    art: dict[str, str],
    stamp_scope: str,
    alive: Callable[[], bool],
) -> dict[str, str] | None:
    """
    Seed/clear a multiart register and reconcile multiart art keys.
    Same-scope serves preserve the frozen snapshot; cross-scope clears it.
    Sole register-state entry point; only the artwork handler may call it.

    :param fadelabel_id: Register control id; None/empty is a no-op.
    :param multiart_dict: Candidate multiart family from the listitem.
    :param art: Processed art dict, updated with multiart keys on seed.
    :param stamp_scope: Scope of this serve, compared to the seed scope.
    :param alive: Focus guard callable; False aborts mid-seed.
    :return: Updated art dict, or None when the guard died mid-seed.
    """
    if not fadelabel_id:
        return art
    seed_scope_key = f"multiart_seed_scope_{fadelabel_id}"
    same_scope = infolabel(f"Window(home).Property({seed_scope_key})") == stamp_scope
    seeded = False
    if len(multiart_dict) > 1:
        ordered = order_multiart(multiart_dict)
        seeded = set_multiart_fadelabel(
            fadelabel_id=fadelabel_id,
            ordered=ordered,
            alive=alive,
            preserve_frozen=same_scope,
        )
    if seeded:
        art |= sequence_to_multiart_dict(ordered)
    elif alive():
        clear_label(fadelabel_id, hide=False)
        if not same_scope:
            window_property(f"multiart_frozen_{fadelabel_id}")
        art = {k: v for k, v in art.items() if not k.startswith("multiart")}
    else:
        return None
    if alive():
        window_property(seed_scope_key, stamp_scope)
    return art
