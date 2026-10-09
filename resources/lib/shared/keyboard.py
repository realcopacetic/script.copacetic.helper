# author: realcopacetic


from xml.etree.ElementTree import Element, ElementTree

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


def usable_layouts(tree: ElementTree) -> list[Element]:
    """
    Return a keyboardlayout file's layouts, skipping coding-table ones (CJK input).

    :param tree: ElementTree of one keyboardlayout file.
    :return: List of layout elements.
    """
    return [
        layout
        for layout in tree.getroot().findall("layout")
        if not layout.get("codingtable")
    ]


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
    layouts = usable_layouts(tree) if tree is not None else []
    if not layouts:
        layouts, variant = usable_layouts(trees["english"]), "ABC"

    def characters(layout) -> tuple[list[str], list[str]]:
        letters, digits = [], []
        keyboard = layout.find("keyboard")
        for row in keyboard.findall("row") if keyboard is not None else []:
            for ch in row.text or "":
                if ch.isalpha() and ch not in letters:
                    letters.append(ch)
                elif ch.isdigit() and ch not in digits:
                    digits.append(ch)
        return letters, digits

    parsed = [(layout.get("layout"), characters(layout)) for layout in layouts]
    letters, digits = next(
        (chars for _, chars in parsed if chars[0] == sorted(chars[0])),
        next((chars for name, chars in parsed if name == variant), parsed[0][1]),
    )
    return (letters + sorted(digits))[:KEYBOARD_CAPACITY]
