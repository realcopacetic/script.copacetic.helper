"""
Every-setting reachability: build a C2 skin once per value of every config option
and expand every window in each build; print the skin's own includes, variables and
expressions no build reaches. ``--json`` saves the union for ``skin_lint --reach``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from build_offline import HELPER, build_isolated, install_stubs
from skin_lint import (
    FIELD,
    GENERATED,
    Node,
    Skin,
    filled_params,
    media_families,
    window_families,
)

if TYPE_CHECKING:  # imported at run time once the stubs are in (state_manager)
    from resources.lib.builders.runtime import RuntimeStateManager

PROBES = ("vue_billboard", "vue_panorama", "vue_reel", "home_bar")  # the method test
EDITOR = "controls (settings editor)"


def state_manager(skin: Path, state: Path, scratch: Path) -> RuntimeStateManager:
    """
    The helper's ``RuntimeStateManager`` over ``skin``'s templates and ``state``,
    with Kodi stubbed.

    :param skin: Skin root.
    :param state: Runtime state file.
    :param scratch: Directory for the stubs' profile paths.
    :return: The manager.
    """
    install_stubs(HELPER, skin, scratch, verbose=False)
    sys.path.insert(0, str(HELPER))
    from resources.lib.builders.runtime import RuntimeStateManager
    from resources.lib.builders.templates import load_template_data_from_source

    templates = load_template_data_from_source(str(skin / "extras/templates"))
    return RuntimeStateManager(*templates, state_path=str(state))


def every_row(manager: RuntimeStateManager) -> dict:
    """
    The default state plus a row for each dynamic mapping item it has none of
    (a widget preset, a menu item), so every item's own config fields are varied.

    :param manager: Manager over the default state.
    :return: Runtime state.
    """
    state = {key: list(rows) for key, rows in manager.runtime_state.items()}
    mappings = manager.mappings

    def depth(key: str) -> int:
        parent = mappings[key].get("parent_mapping")
        return 1 + depth(parent) if parent else 0

    dynamic = [k for k, m in mappings.items() if m.get("mode") == "dynamic"]
    for key in sorted(dynamic, key=depth):
        rows = state.setdefault(key, [])
        present = {row["mapping_item"] for row in rows}
        new = [
            manager._build_default_entry(key, item, deterministic=True)
            for item in mappings[key]["items"]
            if item not in present
        ]
        if parent := mappings[key].get("parent_mapping"):
            hosts = {row["mapping_item"]: row["runtime_id"] for row in state[parent]}
            # no parent row named by metadata: one that seeds this mapping, or the first
            host = next(
                (i for i in hosts.values() if manager.default_children(key, i)),
                next(iter(hosts.values())),
            )
            for row in new:
                row["parent"] = hosts.get(row.get("parent"), host)
        rows += new
    return state


def written_fields(skin: Path) -> set[str]:
    """
    The row fields the settings editor writes: each control's ``field`` (else
    ``mapping_item``) and its browse's sibling controls'. A row stores no other.

    :param skin: Skin root.
    :return: Field names, any mapping's.
    """
    controls = [
        (name, control)
        for path in sorted((skin / "extras/templates/controls").glob("*.json"))
        for name, control in json.loads(path.read_text("utf-8"))["controls"].items()
    ]
    written = {control.get("field") or "mapping_item" for _, control in controls}
    for _, control in controls:
        onclick = control.get("onclick") or {}
        for sibling in onclick.get("sibling_fields", {}).values():
            named = {c.get("field", sibling) for n, c in controls if n == sibling}
            written |= named or {sibling}
    return written


def variants(
    manager: RuntimeStateManager, state: dict, written: set[str]
) -> dict[str, dict]:
    """
    One state per option value that some row keeps and changes, set on every such
    row; then, for a field with ``dependent_fields``, one per value of each of them.

    :param manager: Manager over the templates.
    :param state: Base runtime state.
    :param written: Fields the editor writes; any other only takes its default.
    :return: {label: runtime state}, every single option before any pair.
    """
    found = {1: {}, 2: {}}
    for key, rows in state.items():
        placeholder = manager.mappings[key].get("placeholders", {}).get("key", "")
        resolved = [manager._fill_defaults(key, row) for row in rows]

        def allowed(row: dict, field: str, template: str, given: tuple) -> list[tuple]:
            done = manager._fill_defaults(key, {**row, **dict(given)})
            sub = {k: v for k, v in done.items() if isinstance(v, str)}
            sub[placeholder] = row["mapping_item"]
            items = manager.configs.resolve(key, template, sub).get("items", [])
            # a {…} is rendered only in a default: no stored value holds one
            return [(*given, (field, v)) for v in items if not FIELD.search(v)]

        singles, pairs = {}, {}  # a pair runs only if it gives a state no single does
        for row in rows:
            seeded = manager._seed_fields_for(key, row["mapping_item"])
            # a field the editor never writes takes its default, from its deps
            seeds = {f: t for f, t in seeded.items() if f in written}
            for field, template in seeds.items():
                singles.update(dict.fromkeys(allowed(row, field, template, ())))
                deps = manager.configs.dependent_fields(key, template)
                for dep in (d for d in deps if d in seeds):
                    for given in allowed(row, dep, seeds[dep], ()):
                        pairs.update(
                            dict.fromkeys(allowed(row, field, template, given))
                        )
        options = singles | pairs
        # an option that resolves every row as one before it (a dependent value its
        # parent's alone sets) builds nothing new
        seen = {json.dumps(resolved, sort_keys=True)}
        for option in options:
            new, outcome = [], []
            for row, done in zip(rows, resolved):
                entry = {**row, **dict(option)}
                kept = manager._fill_defaults(key, entry)
                if all(kept.get(f) == v for f, v in option):
                    new.append(entry)
                    outcome.append(kept)
                else:
                    new.append(row)
                    outcome.append(done)
            if (outcome := json.dumps(outcome, sort_keys=True)) not in seen:
                seen.add(outcome)
                label = ", ".join(f"{f}={v}" for f, v in option)
                found[len(option)][f"{key}: {label}"] = {**state, key: new}
    return found[1] | found[2]


def editor_root(skin: Path) -> Node:
    """
    The settings editor's control templates as a window of labels, a line each:
    the helper resolves their ``$VAR``/``$EXP`` with ``infolabel`` (controls.py).

    :param skin: Skin root.
    :return: The window.
    """
    root = Node("window")
    for path in sorted((skin / "extras/templates/controls").glob("*.json")):
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            label = Node("label")
            label.text, label.src = line, f"{path.name}:{n}"
            root.append(label)
    return root


def reach(skin: Path, generated: Path) -> dict[str, set[tuple[str, str]]]:
    """
    Expand every window of a build as ``skin_lint`` does, C2 windows apart.

    :param skin: Skin root.
    :param generated: ``build_offline`` output.
    :return: (kind, name) sets: "c2" and "all" windows reach, "emitted" generated.
    """
    files = {p.name: p for p in sorted((skin / "16x9").glob("*.xml"))}
    files |= {p.name: p for p in sorted((generated / "16x9").glob("*.xml"))}
    linted = Skin(
        list(files.values()),
        media_families(skin),
        window_families(skin),
        filled_params(skin),
    )
    found = {
        "emitted": {
            (kind, name)
            for kind, defs in linted.defs.items()
            for name, node in defs.items()
            if node.src.startswith(GENERATED)
        }
    }
    if "Timers.xml" in linted.roots:  # Kodi loads it always; its actions' $VARs count
        linted.check_timers(linted.roots["Timers.xml"])
    linted.roots[EDITOR] = editor_root(skin)
    migrated = [*linted.migrated(), EDITOR]
    rest = [
        n for n, r in linted.roots.items() if r.tag == "window" and n not in migrated
    ]
    for label, names in (("c2", migrated), ("all", rest)):  # "all" adds to "c2"
        for name in names:
            linted.resolve_window(name)
        found[label] = linted.reached | {("include", n) for n in linted.included}
    return found


def build(skin: Path, state: dict, out: Path) -> str:
    """
    Build ``skin`` from ``state`` into ``out``.

    :param skin: Skin root.
    :param state: Runtime state.
    :param out: Output directory.
    :return: Digest of the generated XML, to expand each distinct build once.
    """
    out.mkdir()
    path = out / "state.json"
    path.write_text(json.dumps(state))
    build_isolated(skin, out, state=path)
    digest = hashlib.sha1()
    for xml in sorted((out / "16x9").glob("*.xml")):
        digest.update(xml.read_bytes())
    return digest.hexdigest()


def definitions(skin: Path) -> dict[tuple[str, str], str]:
    """
    The skin's own include, variable and expression definitions Kodi registers.

    :param skin: Skin root.
    :return: {(kind, name): file:line}.
    """
    linted = Skin(
        sorted((skin / "16x9").glob("*.xml")), media_families(skin), (), frozenset()
    )
    return {
        (kind, name): node.src
        for kind, defs in linted.defs.items()
        for name, node in defs.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("skin", type=Path, help="skin root directory")
    parser.add_argument("--json", type=Path, help="save reached and unreached names")
    parser.add_argument("--list", action="store_true", help="list variants, no builds")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp, "base")
        build_isolated(args.skin, base)
        manager = state_manager(args.skin, base / "runtime_state.json", Path(tmp))
        state = every_row(manager)
        runs = {"defaults": manager.runtime_state, "every row": state}
        runs |= variants(manager, state, written_fields(args.skin))
        if args.list:
            print("\n".join(runs))
            sys.exit()

        outs = [Path(tmp, str(n)) for n in range(len(runs))]
        builds = {}  # digest: (label, output)
        with ProcessPoolExecutor() as pool:
            digests = pool.map(build, [args.skin] * len(runs), runs.values(), outs)
            for label, out, digest in zip(runs, outs, digests):
                if digest in builds:
                    shutil.rmtree(out)
                else:
                    builds[digest] = label, out
            print(f"{len(runs)} builds, {len(builds)} distinct", flush=True)
            labels, outs = zip(*builds.values())
            defined = definitions(args.skin)
            union = {"c2": set(), "all": set(), "emitted": set()}
            results = pool.map(reach, [args.skin] * len(outs), outs)
            for label, found in zip(labels, results):
                new = sorted(found["c2"] & defined.keys() - union["c2"])
                print(f"{label}: {len(new)} new", flush=True)
                for kind, name in new:
                    print(f"    {kind} {name}")
                for key in union:
                    union[key] |= found[key]

    unreached = {k: src for k, src in defined.items() if k not in union["c2"]}
    print("\nmethod test, C2 windows:")
    for name in PROBES:
        print(f"  {name}: {'reached' if ('include', name) in union['c2'] else 'NOT'}")
    print(
        f"\n{len(unreached)} of {len(defined)} skin definitions no C2 window reaches:"
    )
    for (kind, name), src in sorted(unreached.items(), key=lambda i: i[1]):
        elsewhere = (kind, name) in union["all"]
        note = " (an unmigrated window reaches it)" if elsewhere else ""
        print(f"  {src}  {kind} {name}{note}")
    unread = sorted(union["emitted"] - union["all"])
    print(f"\n{len(unread)} generated names some build emits and no build reads")
    if args.json:
        saved = {
            key: sorted(" ".join(k) for k in names) for key, names in union.items()
        }
        args.json.write_text(json.dumps(saved, indent=1))


if __name__ == "__main__":
    main()
