# author: realcopacetic

from pathlib import Path

import xbmc
import xbmcgui

from resources.lib.service import lyrics, playnext, segments
from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    ADDON,
    ADDONDATA,
    condition,
    infolabel,
    json_call,
)

# Add-ons that do a job the helper's features do: the features (skin settings) they
# overlap, and the question asked about each
CLASHES = {
    "script.cu.lrclyrics": (lyrics.ENABLED, 32236),
    "service.upnext": (playnext.ENABLED, 32237),
    "plugin.video.tidb": (f"{segments.ENABLED} | {playnext.ENABLED}", 32238),
}
STATE = Path(ADDONDATA) / "clashes.json"
ACTIVE = "!String.IsEmpty(Window(home).Property(helper_active))"  # the service sets it
SETTLED = (
    "Window.IsActive(home) + !System.HasActiveModalDialog + !System.ScreenSaverActive"
)


def _load() -> dict:
    """clashes.json: the answers (id: True to switch it off) and those off for them."""
    data = JSONHandler(STATE).data.get(STATE, {})
    return {"answers": data.get("answers", {}), "off": data.get("off", [])}


def _save(state: dict) -> None:
    """Write clashes.json when the state differs from what it holds."""
    if state != _load():
        JSONHandler(STATE).write_json(state)


def _enable(addon_id: str, enabled: bool) -> None:
    """Switch an add-on on or off; Kodi starts or stops its service with it."""
    json_call(
        "Addons.SetAddonEnabled",
        params={"addonid": addon_id, "enabled": enabled},
        parent="clashes",
    )
    log.info(f"clashes → {addon_id} switched {'on' if enabled else 'off'}")


def _apply(state: dict) -> list[str]:
    """
    Switch off each add-on the user chose to while a feature it overlaps is on, back
    on one switched off that no longer should be; saved if changed.

    :param state: _load's state, updated in place.
    :return: Add-ons on, overlapping a feature on, not asked about yet.
    """
    answers, off = state["answers"], state["off"]
    unasked = []
    for addon_id, (feature, _) in CLASHES.items():
        wanted = condition(feature) and answers.get(addon_id)  # None: not asked
        enabled = condition(f"System.AddonIsEnabled({addon_id})")
        if wanted is None and enabled:
            unasked.append(addon_id)
        elif wanted and enabled:
            _enable(addon_id, False)
            if addon_id not in off:
                off.append(addon_id)
        elif not wanted and addon_id in off:
            _enable(addon_id, True)
            off.remove(addon_id)
    _save(state)
    return unasked


def _settled() -> bool:
    """
    Wait until Home has been on top for 2 s with nothing over it.

    :return: False when Kodi exits or the skin is left first.
    """
    monitor, quiet = xbmc.Monitor(), 0
    while quiet < 4:
        if monitor.waitForAbort(0.5) or not condition(ACTIVE):
            return False
        quiet = quiet + 1 if condition(SETTLED) else 0
    return True


def check() -> None:
    """
    In a skin using the helper: apply the answers given, then, once Home settles, ask
    about each add-on not asked about yet. Only a click on Switch off or Keep both is
    kept: Not now, Back or a close by Kodi asks again next time.
    """
    if not condition(ACTIVE):
        return
    state = _load()
    if not (unasked := _apply(state)) or not _settled():
        return
    skin = infolabel(f"System.AddonTitle({xbmc.getSkinDir()})")
    for addon_id in unasked:
        names = {"addon": infolabel(f"System.AddonTitle({addon_id})"), "skin": skin}
        answer = xbmcgui.Dialog().yesnocustom(
            names["addon"],
            ADDON.getLocalizedString(CLASHES[addon_id][1]) % names,
            ADDON.getLocalizedString(32235),  # custom (2): Keep both
            ADDON.getLocalizedString(32239),  # no (0): Not now
            ADDON.getLocalizedString(32234),  # yes (1): Switch off
        )
        # No button pressed (a quit, a skin reload, Dialog.Close) reads as no (0)
        if answer > 0:
            state["answers"][addon_id] = answer == 1
    _apply(state)


def restore(forget: bool = False) -> None:
    """
    Switch back on every add-on switched off for the skin: in a skin that doesn't use
    the helper, or to ask again.

    :param forget: Forget the answers too, so each is asked again.
    """
    state = _load()
    for addon_id in state["off"]:
        _enable(addon_id, True)
    _save({"answers": {} if forget else state["answers"], "off": []})
