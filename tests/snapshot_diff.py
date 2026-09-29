"""
Build a skin at a base git ref and at its working tree (or a head ref),
then diff the generated outputs. Exits 1 on any difference.

The golden is the base ref's build; nothing is committed.
"""

import argparse
import difflib
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from build_offline import HELPER, build_isolated, fail

SKIN_PATHS = ("addon.xml", "extras/templates")
HELPER_PATHS = ("addon.xml", "resources")


def export(repo: Path, ref: str, paths: tuple[str, ...], dest: Path) -> Path:
    """
    Extract ``paths`` of ``repo`` at ``ref`` into ``dest`` via ``git archive``;
    exit 2 if git fails.

    :param repo: Git working tree.
    :param ref: Any commit-ish.
    :param paths: Repo-relative paths to export.
    :param dest: Empty target directory.
    :return: ``dest``.
    """
    cmd = ["git", "-C", str(repo), "archive", "--format=tar", ref, "--", *paths]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode:
        fail(result.stderr.decode())
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(dest, filter="data")
    return dest


def diff_trees(base: Path, head: Path, context: int) -> list[str]:
    """
    Unified diff of every file under two output directories.

    :param base: Base output directory.
    :param head: Head output directory.
    :param context: Context lines per hunk.
    :return: Diff lines; empty when identical.
    """
    files = {
        p.relative_to(root)
        for root in (base, head)
        for p in root.rglob("*")
        if p.is_file()
    }
    lines = []
    for rel in sorted(files):
        a, b = (
            (
                (root / rel).read_text("utf-8").splitlines()
                if (root / rel).exists()
                else []
            )
            for root in (base, head)
        )
        lines += difflib.unified_diff(
            a, b, f"base/{rel}", f"head/{rel}", n=context, lineterm=""
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("skin", type=Path, help="skin git working tree")
    parser.add_argument("--base", default="HEAD", help="skin base ref (HEAD)")
    parser.add_argument("--head", help="skin head ref (default: working tree)")
    parser.add_argument("--helper-base", help="helper ref for the base build")
    parser.add_argument("--state", type=Path, help="runtime_state.json for both")
    parser.add_argument("-U", "--context", type=int, default=1, help="context lines")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        base_skin = export(args.skin, args.base, SKIN_PATHS, tmp / "base_skin")
        head_skin = (
            export(args.skin, args.head, SKIN_PATHS, tmp / "head_skin")
            if args.head
            else args.skin
        )
        base_helper = (
            export(HELPER, args.helper_base, HELPER_PATHS, tmp / "base_helper")
            if args.helper_base
            else HELPER
        )
        for side, skin, helper in (
            ("base", base_skin, base_helper),
            ("head", head_skin, HELPER),
        ):
            print(f"{side}: {build_isolated(skin, tmp / side, helper, args.state)}")
        lines = diff_trees(tmp / "base", tmp / "head", args.context)

    print("\n".join(lines) or "no differences")
    sys.exit(bool(lines))


if __name__ == "__main__":
    main()
