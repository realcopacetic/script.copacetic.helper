# author: realcopacetic

from pathlib import Path
from uuid import uuid4

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
ASKING = "helper_clashes_asking"  # Home property: the running check's token
SETTLED = (
    "Window.IsActive(home) + !System.HasActiveModalDialog + !System.ScreenSaverActive"
)
# Writes a script hands the service (JSONRPC.NotifyAll), so they never overlap
ANSWERS, RESET = "clashes_answers", "clashes_reset"


def features() -> tuple[tuple[bool, str], ...]:
    """
    Each feature in CLASHES on or not, and its add-on's version ("" while off): for
    the service to see a feature turned on or off, or an add-on switched or updated.
    """
    return tuple(
        (condition(feature), _version(addon_id))
        for addon_id, (feature, _) in CLASHES.items()
    )


def _load() -> dict:
    """
    clashes.json: the answers (id: True to switch it off) and those off for them, with
    the version each had then (None from a list, written before versions were kept).
    """
    data = JSONHandler(STATE).data.get(STATE, {})
    off = data.get("off", {})
    return {
        "answers": data.get("answers", {}),
        "off": dict.fromkeys(off) if isinstance(off, list) else off,
    }


def _save(state: dict) -> None:
    """Write clashes.json when the state differs from what it holds."""
    if state != _load():
        JSONHandler(STATE).write_json(state)


def _enable(addon_id: str, enabled: bool) -> bool:
    """
    Switch an add-on on or off; Kodi starts or stops its service with it.

    :param addon_id: Add-on id.
    :param enabled: True to switch it on.
    :return: False when Kodi refuses (an add-on uninstalled, or one it can't switch).
    """
    switch = "on" if enabled else "off"
    if done := "result" in json_call(
        "Addons.SetAddonEnabled",
        params={"addonid": addon_id, "enabled": enabled},
        parent="clashes",
    ):
        log.info(f"clashes → {addon_id} switched {switch}")
    else:
        log.warning(f"clashes → {addon_id} not switched {switch}: Kodi refused")
    return done


def _version(addon_id: str) -> str:
    """
    An add-on's version, read fresh (a condition holds its value for the frame).

    :param addon_id: Add-on id.
    :return: "" while it is off or not installed.
    """
    return infolabel(f"System.AddonVersion({addon_id})")


def _unasked(answers: dict) -> list[str]:
    """
    The add-ons to ask about.

    :param answers: The answers given: id: True to switch it off.
    :return: Add-ons on, overlapping a feature on, not asked about yet.
    """
    return [
        addon_id
        for addon_id, (feature, _) in CLASHES.items()
        if addon_id not in answers and condition(feature) and _version(addon_id)
    ]


def apply(answers: dict | None = None) -> list[str]:
    """
    The service's write, so two never overlap: merge new answers, switch off each
    add-on chosen while a feature it overlaps is on, back on one no longer wanted off.
    One found on at the version it went off at, or unknown, was switched on: kept.

    :param answers: Answers just clicked: id: True to switch it off.
    :return: Add-ons on, overlapping a feature on, not asked about yet.
    """
    state = _load()
    state["answers"] |= answers or {}
    answers, off = state["answers"], state["off"]
    for addon_id, (feature, _) in CLASHES.items():
        wanted = condition(feature) and answers.get(addon_id)  # None: not asked
        version = _version(addon_id)  # "" while off
        if addon_id in off and not condition(f"System.HasAddon({addon_id})"):
            del off[addon_id]  # uninstalled while off: nothing to give back
        elif (
            wanted and version and addon_id in off and off[addon_id] in (None, version)
        ):
            answers[addon_id] = False
            del off[addon_id]
            log.info(f"clashes → {addon_id} switched back on elsewhere, kept")
        elif wanted and version:
            # Not off yet, or an install or update switched it back on (LoadAddon)
            if _enable(addon_id, False):
                off[addon_id] = version
        elif not wanted and addon_id in off:
            if _enable(addon_id, True):
                del off[addon_id]
    _save(state)
    return _unasked(answers)


def notify(message: str, data: dict | None = None) -> None:
    """
    Hand the service a write: its Monitor runs onNotification on its own thread.

    :param message: ANSWERS or RESET.
    :param data: For ANSWERS, the answers clicked.
    """
    json_call(
        "JSONRPC.NotifyAll",
        params={"sender": "script.copacetic.helper", "message": message, "data": data},
        parent="clashes",
    )


def _current(token: str) -> bool:
    """
    Whether this check is still the one to run.

    :param token: The guard's value this check set.
    :return: False once the skin is left or the guard changes hands.
    """
    return condition(ACTIVE) and xbmcgui.Window(10000).getProperty(ASKING) == token


def _settled(token: str) -> bool:
    """
    Wait until Home has been on top for 2 s with nothing over it.

    :param token: The guard's value this check set.
    :return: False when Kodi exits, the skin is left or the guard changes hands first.
    """
    monitor, quiet = xbmc.Monitor(), 0
    while quiet < 4:
        if monitor.waitForAbort(0.5) or not _current(token):
            return False
        quiet = quiet + 1 if condition(SETTLED) else 0
    return True


def _ask(unasked: list[str], token: str) -> dict:
    """
    Ask about each add-on in turn, until the skin is left or the guard changes hands.
    Only a click on Switch off or Keep both counts: Not now, Back or a close by Kodi
    asks again next time.

    :param unasked: Add-on ids to ask about.
    :param token: The guard's value this check set.
    :return: Each answer clicked: id: True to switch it off.
    """
    skin = infolabel(f"System.AddonTitle({xbmc.getSkinDir()})")
    answers = {}
    for addon_id in unasked:
        if not _current(token):
            break
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
            answers[addon_id] = answer == 1
    return answers


def check() -> None:
    """
    In a skin using the helper, once Home settles, ask about each add-on not asked
    about yet; the service applies the answers. One check runs at a time.
    """
    home = xbmcgui.Window(10000)
    if not condition(ACTIVE) or home.getProperty(ASKING):
        # The running one asks about those unasked once Home settles; one that needs
        # asking about after its questions open waits for the next check
        return
    # A token, so a check outlived by a helper restart stops and leaves the new guard
    token = uuid4().hex
    home.setProperty(ASKING, token)
    try:
        if not _unasked(_load()["answers"]) or not _settled(token):
            return
        # Read again after the wait: a reset may land meanwhile
        if answers := _ask(_unasked(_load()["answers"]), token):
            notify(ANSWERS, answers)
    finally:
        if home.getProperty(ASKING) == token:
            home.clearProperty(ASKING)


def restore(forget: bool = False) -> None:
    """
    Switch back on every add-on switched off for the skin: in a skin that doesn't use
    the helper, or to ask again. One Kodi refuses stays listed; one uninstalled goes.

    :param forget: Forget the answers too, so each is asked again.
    """
    state = _load()
    off = {
        addon_id: version
        for addon_id, version in state["off"].items()
        if condition(f"System.HasAddon({addon_id})") and not _enable(addon_id, True)
    }
    _save({"answers": {} if forget else state["answers"], "off": off})
