# author: realcopacetic
"""Byte-compare generated builder outputs against a committed snapshot."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FILES = (
    "script-copacetic-helper_variables.xml",
    "script-copacetic-helper_expressions.xml",
    "script-copacetic-helper_includes.xml",
)


def normalised(path: Path) -> bytes:
    """
    Canonical form: top-level children sorted by name attribute.

    :param path: XML file to normalise.
    :return: Serialised canonical bytes.
    """
    root = ET.parse(path).getroot()
    root[:] = sorted(root, key=lambda e: (e.get("name") or "").casefold())
    ET.indent(root, space="  ")
    return ET.tostring(root)


def main() -> int:
    """
    Compare current outputs to snapshot; --normalised for order-insensitive mode.

    :return: 0 when identical, 1 otherwise.
    """
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    norm = "--normalised" in sys.argv
    current, snapshot = Path(args[0]), Path(args[1])
    failed = False
    for name in FILES:
        a, b = current / name, snapshot / name
        same = (
            normalised(a) == normalised(b) if norm else a.read_bytes() == b.read_bytes()
        )
        print(f"{'OK  ' if same else 'DIFF'} {name}")
        failed |= not same
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
