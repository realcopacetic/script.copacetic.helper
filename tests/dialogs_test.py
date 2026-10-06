"""
A menu of every dialog, window and notification Python can open; Back closes it.

Runs inside Kodi: ``RunScript(<path to this file>)``, e.g. from a keymap. Each
entry's label says what to look at; the menu itself is the simple Select.
"""

import json
import os
import runpy

import xbmc
import xbmcaddon
import xbmcgui

L = xbmc.getLocalizedString
DIALOG = xbmcgui.Dialog()
ADDON = xbmcaddon.Addon("script.copacetic.helper")
ICON = ADDON.getAddonInfo("icon")
FANART = os.path.join(ADDON.getAddonInfo("path"), "resources", "fanart.jpg")
LONG_TEXT = " ".join(["Long text scrolls by itself after a pause."] * 40)


def listitems(count: int) -> list[xbmcgui.ListItem]:
    """
    Rows with a second label and art, for the detailed lists.

    :param count: number of rows.
    :return: the list items.
    """
    rows = []
    for n in range(1, count + 1):
        item = xbmcgui.ListItem(f"Item {n}", f"Second label {n}")
        item.setArt({"icon": ICON, "thumb": ICON, "poster": ICON, "fanart": FANART})
        rows.append(item)
    return rows


def wait_closed(window: str) -> None:
    """
    Wait for a window opened by a builtin, which returns before it shows.

    :param window: Kodi window name.
    """
    xbmc.sleep(500)
    while xbmc.getCondVisibility(f"Window.IsVisible({window})"):
        xbmc.sleep(200)


def video_info() -> None:
    """Video info for a non-library item, so only what the ListItem carries shows."""
    item = xbmcgui.ListItem("Video info · non-library item")
    item.setArt({"poster": ICON, "fanart": FANART, "thumb": ICON})
    tag = item.getVideoInfoTag()
    tag.setTitle("Video info · non-library item")
    tag.setYear(2026)
    tag.setPlot(LONG_TEXT)
    tag.setMediaType("movie")
    DIALOG.info(item)


def notifications() -> None:
    """The three stock icons, then the helper's icon with a long message."""
    for icon, name in (
        (xbmcgui.NOTIFICATION_INFO, "info"),
        (xbmcgui.NOTIFICATION_WARNING, "warning"),
        (xbmcgui.NOTIFICATION_ERROR, "error"),
    ):
        DIALOG.notification("Notification", f"Stock {name} icon", icon, 3000)
        xbmc.sleep(3500)
    DIALOG.notification("Notification · custom icon", LONG_TEXT, ICON, 8000)
    xbmc.sleep(8500)


def background_progress() -> None:
    """The extended progress pill, stepping back for a notification halfway."""
    bar = xbmcgui.DialogProgressBG()
    bar.create("Background progress", "Pill in the centre berth")
    for percent in range(101):
        bar.update(percent, message=f"{percent}%")
        if percent == 50:
            DIALOG.notification(
                "Over progress", "The progress pill fades out until I go"
            )
        xbmc.sleep(150)  # 15 s: the 5 s toast leaves the pill on show both sides
    bar.close()


def busy() -> None:
    """The busy spinner for three seconds; host content should stay up behind it."""
    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    xbmc.sleep(3000)
    xbmc.executebuiltin("Dialog.Close(busydialognocancel)")


def volume_bar() -> None:
    """The volume pill, at the current volume so nothing changes."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "Application.GetProperties",
        "params": {"properties": ["volume"]},
    }
    volume = json.loads(xbmc.executeJSONRPC(json.dumps(request)))["result"]["volume"]
    xbmc.executebuiltin(f"SetVolume({volume},showVolumeBar)")
    xbmc.sleep(3000)


def shutdown_menu() -> None:
    """The shutdown menu; back out of it to return here."""
    xbmc.executebuiltin("ActivateWindow(shutdownmenu)")
    wait_closed("shutdownmenu")


CASES = (
    (
        "Select · detailed rows with art (thumbnail berth)",
        lambda: DIALOG.select("Select · detailed", listitems(12), useDetails=True),
    ),
    (
        "Select · multi-select (OK shows the check)",
        lambda: DIALOG.multiselect(
            "Multi-select", [f"Item {n}" for n in range(1, 13)], preselect=[0, 2]
        ),
    ),
    (
        "Context menu",
        lambda: DIALOG.contextmenu([f"Option {n}" for n in range(1, 9)]),
    ),
    (
        "FileBrowser · folder",
        lambda: DIALOG.browseSingle(0, "FileBrowser · folder", "files"),
    ),
    (
        "FileBrowser · images, starts in the skin's media (thumbs view)",
        lambda: DIALOG.browseSingle(
            2, "FileBrowser · images", "pictures", defaultt="special://skin/media/"
        ),
    ),
    (
        "FileBrowser · several files",
        lambda: DIALOG.browseMultiple(1, "FileBrowser · several files", "files"),
    ),
    ("Keyboard · text", lambda: DIALOG.input("Keyboard · text", "Copacetic")),
    (
        "Keyboard · hidden input",
        lambda: DIALOG.input("Keyboard · hidden", option=xbmcgui.ALPHANUM_HIDE_INPUT),
    ),
    ("Numeric · number", lambda: DIALOG.numeric(0, "Numeric · number")),
    ("Numeric · date", lambda: DIALOG.numeric(1, "Numeric · date")),
    ("Numeric · IP address", lambda: DIALOG.numeric(3, "Numeric · IP address")),
    ("Text viewer", lambda: DIALOG.textviewer("Text viewer", LONG_TEXT)),
    ("Colour picker", lambda: DIALOG.colorpicker("Colour picker", "FFF2B4C4")),
    ("Video info · non-library item", video_info),
    ("Add-on settings (this helper)", ADDON.openSettings),
    ("Shutdown menu", shutdown_menu),
    ("Notifications", notifications),
    ("Background progress", background_progress),
    ("Busy spinner", busy),
    ("Volume bar", volume_bar),
    (
        "Confirm dialogs (confirm_test.py)",
        lambda: runpy.run_path(
            os.path.join(os.path.dirname(__file__), "confirm_test.py")
        ),
    ),
)


def main() -> None:
    """Show the menu until Back, running the chosen case each time."""
    labels = [label for label, _ in CASES]
    choice = 0
    while (choice := DIALOG.select("Dialog tests", labels, preselect=choice)) >= 0:
        CASES[choice][1]()


main()
