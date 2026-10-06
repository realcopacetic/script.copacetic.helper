"""
Open every DialogConfirm variant in turn; each heading names what to check.

Runs inside Kodi: ``RunScript(<path to this file>)``, e.g. from a keymap.
"""

import xbmc
import xbmcgui

L = xbmc.getLocalizedString
dialog = xbmcgui.Dialog()

dialog.yesno(
    "1 · Yes/no",
    "Stock labels: × then ✓, focus starts on × with a No pill; Left/Right wrap.",
)
dialog.yesnocustom(
    "2 · Three buttons", "No / Settings / Yes: the gear sits in the middle.", L(10004)
)
dialog.yesno(
    "3 · Known labels",
    "Remove / Keep: Trash and Check icons.",
    nolabel=L(15015),
    yeslabel=L(15014),
)
dialog.yesno(
    "4 · Known labels",
    "Single file / Separate: FileText and Files icons.",
    nolabel=L(20428),
    yeslabel=L(20429),
)
dialog.yesno(
    "5 · Unknown labels",
    "Labels outside the list: text buttons, focused one underlined.",
    nolabel="Not now",
    yeslabel="Install",
)
dialog.yesnocustom(
    "6 · Unknown custom",
    "Cancel is known, Changelog and Update aren't: text buttons.",
    "Changelog",
    L(222),
    "Update",
)
dialog.ok(
    "7 · OK only, long text",
    " ".join(["Ten whole lines, then it scrolls by itself after a pause."] * 16),
)

progress = xbmcgui.DialogProgress()
progress.create(
    "8 · Progress", "4px fill on a 2px track, percentage after the heading, Cancel."
)
for percent in range(101):
    if progress.iscanceled():
        break
    progress.update(percent, f"Step {percent} of 100")
    if percent == 50:
        dialog.yesno(
            "9 · Over progress", "The progress dialog behind this one should be hidden."
        )
    xbmc.sleep(60)
progress.close()
