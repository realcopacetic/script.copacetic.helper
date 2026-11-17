"""
Build a skin from runtime states with each mapping emptied in turn, then all at once:
the builder must cope with no rows (zero widgets once crashed it, 4 Nov 2026).
Exits 2 at the first state whose build fails or logs an error.
"""

import argparse
import json
import tempfile
from pathlib import Path
from typing import Iterator

from build_offline import build_isolated


def emptied(state: dict[str, list]) -> Iterator[tuple[str, dict[str, list]]]:
    """
    Yield ``state`` with one mapping's rows removed, for each mapping, then with all.

    :param state: Runtime state, {mapping: rows}.
    :return: ``(label, state)`` pairs; the label names the mapping, or ``all``.
    """
    for name in state:
        yield name, state | {name: []}
    yield "all", dict.fromkeys(state, [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("skin", type=Path, help="skin root directory")
    parser.add_argument(
        "--state", type=Path, help="runtime_state.json to empty (default: seeded)"
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        state = args.state
        if state is None:
            build_isolated(args.skin, tmp / "seed")
            state = tmp / "seed" / "runtime_state.json"
        for label, rows in emptied(json.loads(state.read_text())):
            path = tmp / f"{label}.json"
            path.write_text(json.dumps(rows))
            print(f"{label}:", end=" ", flush=True)
            print(build_isolated(args.skin, tmp / label, state=path))


if __name__ == "__main__":
    main()
