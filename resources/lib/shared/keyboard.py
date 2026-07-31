# author: realcopacetic

import xbmcvfs

from resources.lib.shared.xml import XMLHandler

KEYBOARD_LAYOUTS = "special://xbmc/system/keyboardlayouts"
KEYBOARD_CAPACITY = 48


def keyboard_layout_trees() -> dict:
    """
    Read all Kodi keyboardlayout files via the shared XML handler.

    :return: Dict of language stem to ElementTree.
    """
    return XMLHandler(xbmcvfs.translatePath(KEYBOARD_LAYOUTS)).data


def layout_characters(layout_id: str, trees: dict) -> list[str]:
    """
    Extract letters-then-digits from a Kodi keyboardlayout, preferring the
    alphabetical variant of the layout's language file.

    :param layout_id: Kodi layout identifier (e.g. "Russian АБВ").
    :param trees: Dict of language stem to ElementTree from keyboard_layout_trees.
    :return: Ordered list of characters, capped at KEYBOARD_CAPACITY.
    """
    language, _, variant = layout_id.partition(" ")
    tree = trees.get(language.lower())
    if tree is None:
        tree, variant = trees["english"], "ABC"

    layouts = [
        layout
        for layout in tree.getroot().findall("layout")
        if not layout.get("codingtable")
    ]
    if not layouts:
        tree, variant = trees["english"], "ABC"
        layouts = [
            layout
            for layout in tree.getroot().findall("layout")
            if not layout.get("codingtable")
        ]

    def characters(layout):
        letters, digits = [], []
        keyboard = layout.find("keyboard")
        for row in keyboard.findall("row") if keyboard is not None else []:
            for ch in row.text or "":
                if ch.isalpha() and ch not in letters:
                    letters.append(ch)
                elif ch.isdigit() and ch not in digits:
                    digits.append(ch)
        return letters, digits

    chosen = next(
        (l for l in layouts if characters(l)[0] == sorted(characters(l)[0])),
        next((l for l in layouts if l.get("layout") == variant), layouts[0]),
    )
    letters, digits = characters(chosen)
    return (letters + sorted(digits))[:KEYBOARD_CAPACITY]
