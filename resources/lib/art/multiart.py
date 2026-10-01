# author: realcopacetic

import hashlib
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

DEFAULT_SLOTS = 15
MAX_SLOTS = 50


def build_multiart_dict(
    *,
    target: str,
    multiart_type: str | None,
    max_items: int | str | None,
    tmdb_art: Mapping[str, str],
) -> dict[str, str]:
    """
    Build a multiart dict from local artwork, extended by TMDb artwork of the same
    type. TMDb only extends a local family, so the first image is the item's own.

    :param target: Infolabel prefix such as "ListItem" or "Container(3100).ListItem".
    :param multiart_type: Base art type (e.g. "fanart", "poster", "keyart").
    :param max_items: Maximum number of multiart slots to read.
    :param tmdb_art: TMDb art dict ("fanart", "fanart1" …); empty for none.
    :return: A dict mapping "multiart" and "multiartN" keys to artwork URLs.
    """
    if not multiart_type:
        return {}

    local_seq = multiart_sequence_from_infolabels(
        target=target,
        art_type=multiart_type,
        max_items=max_items,
    )
    tmdb_seq = (
        multiart_sequence_from_dict(
            art=tmdb_art,
            art_type=multiart_type,
            max_items=max_items,
        )
        if local_seq
        else []
    )
    merged = merge_multiart_sequences(primary=local_seq, secondary=tmdb_seq)
    return sequence_to_multiart_dict(merged)


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
    merged = []
    seen = set()

    for url in (*primary, *secondary):
        if url and url not in seen:
            merged.append(url)
            seen.add(url)

    return merged


def sequence_to_multiart_dict(urls: Iterable[str]) -> dict[str, str]:
    """
    Turn a list of URLs into the standard multiart dict: urls[0] → "multiart",
    urls[1] → "multiart1", urls[2] → "multiart2", and so on.
    """
    seq = [u for u in urls if u]
    if not seq:
        return {}

    result = {"multiart": seq[0]}
    for index, url in enumerate(seq[1:], start=1):
        result[f"multiart{index}"] = url

    return result


def order_multiart(art: dict[str, str]) -> list[str]:
    """
    Resolve the display order for a multiart dict: main image first, extras shuffled.

    :param art: Dict from sequence_to_multiart_dict ("multiart" first).
    :return: Ordered list of URLs, main first.
    """
    main, *extras = art.values()
    random.shuffle(extras)
    return [main, *extras]


def set_multiart_fadelabel(
    fadelabel_id: int | str,
    ordered: list[str],
    *,
    alive: Callable[[], bool] | None = None,
    preserve_frozen: bool = True,
) -> bool:
    """
    Seed a FadeLabel control with a multiart sequence. Parking the displayed frame
    in multiart_frozen is skipped on cross-container serves, where it belongs to the
    previous region and would contaminate the scroll fallback.

    :param fadelabel_id: Control id of the FadeLabel to populate.
    :param ordered: URLs in display order (see order_multiart).
    :param alive: Focus guard; seeding aborts if it returns False after the park.
    :param preserve_frozen: Park the displayed frame in multiart_frozen; False skips it.
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
        ctrl.reset()
        # reset() keeps the rotation index until Process clamps it (GetLabel reads
        # empty till then), so the main image reading back proves the clamp.
        ctrl.addLabel(ordered[0])
        monitor = Monitor()
        for _ in range(5):  # bounded: with a modal dialog up, Python reads the dialog
            if infolabel(f"Control.GetLabel({fadelabel_id})") == ordered[0]:
                break
            if monitor.waitForAbort(0.02):
                return False
        if alive and not alive():
            return False
        for label in ordered[1:]:
            ctrl.addLabel(label)

    except Exception as e:
        log.warning(f"Unable to set multiart fadelabel → {e}")
        return False

    return True


def _multiart_signature(multiart_dict: dict[str, str]) -> str:
    """
    Order-independent digest of a multiart candidate set.
    Compared pre-shuffle: the seeded order is randomised per serve,
    so identity must be judged on the set, not the sequence.

    :param multiart_dict: Candidate multiart family from the listitem.
    :return: Hex digest identifying the set.
    """
    payload = "\n".join(sorted(multiart_dict.values()))
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def seed_multiart(
    *,
    fadelabel_id: str | None,
    multiart_dict: dict[str, str],
    art: dict[str, str],
    seed_scope: str,
    seed_item: str,
    alive: Callable[[], bool],
) -> dict[str, str] | None:
    """
    Seed/clear a multiart register and reconcile multiart art keys. Register identity
    is the listing (region + folder), not the item: same-listing serves preserve the
    frozen snapshot, any other clears it. Sole entry point (artwork handler only).

    :param fadelabel_id: Register control id; None/empty is a no-op.
    :param multiart_dict: Candidate multiart family from the listitem.
    :param art: Processed art dict, updated with multiart keys on seed.
    :param seed_scope: Listing identity of this serve (region@folder).
    :param seed_item: Item identity of this serve (pos/dbid); keys the skip.
    :param alive: Focus guard callable; False aborts mid-seed.
    :return: Updated art dict, or None when the guard died mid-seed.
    """

    if not fadelabel_id:
        return art
    seed_scope_key = f"multiart_seed_scope_{fadelabel_id}"
    same_scope = infolabel(f"Window(home).Property({seed_scope_key})") == seed_scope
    sig_key = f"multiart_seed_sig_{fadelabel_id}"
    signature = f"{seed_item}:{_multiart_signature(multiart_dict)}"
    # Interruptor guard: a refire that would reseed the identical set for the
    # SAME item into a live register (announcement invalidation, viewmenu
    # return) is a pure no-op — the rotation continues untouched. A new item
    # always reseeds, even into an identical set, so every arrival restarts on
    # the main image. A legitimately cleared register has an empty label and
    # never skips; a scope change never skips.
    if (
        len(multiart_dict) > 1
        and same_scope
        and infolabel(f"Window(home).Property({sig_key})") == signature
        and infolabel(f"Control.GetLabel({fadelabel_id})")
    ):
        log.debug(
            f"seed_multiart → skip: register {fadelabel_id} already carries this set"
        )
        return art
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
        log.debug(
            f"seed_multiart → seeded register {fadelabel_id} ({len(ordered)} items)"
        )
    elif alive():
        clear_label(fadelabel_id)
        if not same_scope:
            window_property(f"multiart_frozen_{fadelabel_id}")
        art = {k: v for k, v in art.items() if not k.startswith("multiart")}
    else:
        return None
    if alive():
        window_property(seed_scope_key, seed_scope)
        if seeded:
            window_property(sig_key, signature)
        else:
            window_property(sig_key)
    return art
