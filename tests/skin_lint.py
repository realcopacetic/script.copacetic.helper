"""
Lint a skin's ``16x9/*.xml`` together with freshly generated helper outputs.

Mirrors Omega's ``CGUIIncludes`` load and resolve rules. By default only what
the migrated (C2) windows load is checked; ``--all`` checks everything. Errors exit 1.
"""

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, NamedTuple
from xml.parsers import expat

from build_offline import build_isolated

REF = re.compile(r"\$(?:ESC)?(VAR|EXP)\[((?:[^\[\]]|\[[^\[\]]*\])+)\]")
PARAM = re.compile(r"\$PARAM\[([^\[\]]*)\]")
WHOLE_EXP = re.compile(r"\[?\$EXP\[([^\[\]]+)\]\]?")
KINDS = {"VAR": "variable", "EXP": "expression"}
DEFINITIONS = ("include", "expression", "variable")
LAYOUTS = {"itemlayout", "focusedlayout"}
GENERATED = "script-copacetic-helper_"
UNMIGRATED = ("_addonbrowser", "_pictures")  # pre-built for windows not yet migrated
C2_SHELLS = ("tpl_window", "blk_modal_", "tpl_modal_", "img_modal_", "blk_hud_")
ERRORS = {
    "parse",
    "empty-definition",
    "include-recursion",
    "undefined-expression",
    "undefined-include",
    "undefined-variable",
}


class Node(ET.Element):
    """Element that remembers where it was parsed and which conditions load it."""

    src = "?:0"
    branch = ()


class Finding(NamedTuple):
    rule: str
    src: str
    message: str


def parse(path: Path) -> Node:
    """
    Parse ``path`` keeping line numbers and comments (Kodi counts them as children).

    :param path: XML file.
    :return: Root node.
    """
    builder = ET.TreeBuilder(element_factory=Node, insert_comments=True)
    parser = expat.ParserCreate()
    parser.buffer_text = True

    def start(tag: str, attrs: dict) -> None:
        builder.start(tag, attrs).src = f"{path.name}:{parser.CurrentLineNumber}"

    parser.StartElementHandler = start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.CommentHandler = builder.comment
    with path.open("rb") as file:
        parser.ParseFile(file)
    return builder.close()


def elements(node: Node) -> list[Node]:
    """Child elements of ``node``, comments skipped."""
    return [child for child in node if isinstance(child.tag, str)]


def values(node: Node) -> Iterator[tuple[Node, str]]:
    """Yield ``(element, text or attribute value)`` for ``node``'s whole subtree."""
    for element in node.iter():
        if isinstance(element.tag, str):
            for value in (element.text or "", *element.attrib.values()):
                yield element, value


def params_of(node: Node, attribute: str) -> dict[str, str]:
    """
    Collect ``<param>`` children as ``CGUIIncludes::GetParameters`` does.

    :param node: Include definition or call.
    :param attribute: ``default`` for definitions, ``value`` for calls.
    :return: {name: value}, first occurrence wins.
    """
    params = {}
    for param in node.findall("param"):
        if name := param.get("name"):
            params.setdefault(name, param.get(attribute, param.text or ""))
    return params


def include_name(call: Node) -> str:
    """Name an include call refers to: ``content`` or old-style text."""
    return call.get("content", (call.text or "").strip())


def clone(node: Node) -> Node:
    """Deep copy keeping ``src`` (``copy.deepcopy`` drops the subclass)."""
    if not isinstance(node.tag, str):
        return ET.Comment(node.text)
    new = Node(node.tag, dict(node.attrib))
    new.text, new.tail, new.src = node.text, node.tail, node.src
    new.extend(map(clone, node))
    return new


def controls(node: Node, branch: tuple = ()) -> Iterator[tuple[Node, tuple]]:
    """
    Yield controls with a numeric id and the include conditions above them,
    skipping list item layouts.

    :param node: Expanded window subtree.
    :param branch: Conditions inherited from ancestors.
    """
    for child in elements(node):
        if child.tag in LAYOUTS:
            continue
        path = branch + child.branch
        cid = child.get("id", "")
        if child.tag == "control" and cid.isdigit() and int(cid):
            yield child, path
        yield from controls(child, path)


def exclusive(a: tuple, b: tuple) -> bool:
    """True when two include-condition paths diverge, so they may never load together."""
    return a[: len(b)] != b[: len(a)]


class Skin:
    """Parsed skin files plus the definitions Kodi would register from them."""

    def __init__(self, paths: list[Path]):
        """
        Parse every file, then register definitions from the include files
        ``Includes.xml`` loads, in load order.

        :param paths: XML files to lint.
        """
        self.findings = set()
        self.roots = {}
        for path in paths:
            try:
                self.roots[path.name] = parse(path)
            except expat.ExpatError as e:
                self.report("parse", f"{path.name}:{e.lineno}", str(e))
        self.defs = {kind: {} for kind in DEFINITIONS}
        self.defaults = {}
        self.params = {}
        self.calls = defaultdict(lambda: (set(), set()))
        self.duplicates = defaultdict(list)
        self.reached = set()
        self.loaded = []
        self._load("Includes.xml")
        for name, root in self.roots.items():
            if root.tag == "includes" and name not in self.loaded:
                self.report("unloaded-file", f"{name}:1", "not loaded by Includes.xml")

    def report(self, rule: str, src: str, message: str) -> None:
        """Record one finding; repeats collapse."""
        self.findings.add(Finding(rule, src, message))

    def _load(self, name: str, src: str = "") -> None:
        """Register ``name``'s definitions and load the files it includes."""
        if name in self.loaded:
            return
        if name not in self.roots:
            self.report("undefined-include", src or f"{name}:0", f"file {name}")
            return
        self.loaded.append(name)
        for node in elements(self.roots[name]):
            if node.tag == "include" and "file" in node.attrib:
                self._load(node.get("file"), node.src)
            elif node.tag in DEFINITIONS and node.get("name"):
                self._register(node)

    def _register(self, node: Node) -> None:
        """Register a definition unless Kodi's loader drops it (first one wins)."""
        name = node.get("name")
        if not (len(node) or (node.text or "").strip()):
            self.report("empty-definition", node.src, f"<{node.tag} name={name!r}>")
        elif node.find("param") is not None and node.find("definition") is None:
            self.report("empty-definition", node.src, f"{name!r} has no <definition>")
        elif name not in self.defs[node.tag]:
            self.defs[node.tag][name] = node
            if node.tag == "include":
                self.defaults[name] = params_of(node, "default")
                used = {p for _, value in values(node) for p in PARAM.findall(value)}
                self.params[name] = self.defaults[name].keys() | used

    def body(self, name: str) -> Node:
        """Included part of an include definition."""
        node = self.defs["include"][name]
        definition = node.find("definition")
        return node if definition is None else definition

    def check_reference(self, token: str, name: str, src: str) -> None:
        """Report a ``$VAR``/``$EXP`` with no definition; ``$PARAM`` names skip."""
        kind = KINDS[token]
        if kind == "variable":
            name = name.split(",")[0]
        if "$" not in name and name not in self.defs[kind]:
            self.report(f"undefined-{kind}", src, f"${token}[{name}]")

    def check_references(self, root: Node) -> None:
        """Check every literal ``$VAR``/``$EXP`` reference in ``root``."""
        for node, value in values(root):
            for token, name in REF.findall(value):
                self.check_reference(token, name, node.src)

    def check_calls(self, root: Node) -> None:
        """Report unknown includes and params their definition never mentions."""
        tops = elements(root) if root.tag == "includes" else [root]
        for call in (c for top in tops for c in top.iter("include") if c is not top):
            name = include_name(call)
            if "file" in call.attrib or "$" in name:
                continue
            if name not in self.defs["include"]:
                self.report("undefined-include", call.src, name or "(no name)")
                continue
            self.record_call(call, name)

    def record_call(self, call: Node, name: str) -> None:
        """Record the include ``call`` reached and the params it passed."""
        targets, passed = self.calls[call.src]
        targets.add(name)
        passed.update(params_of(call, "value"))

    def check_params(self) -> None:
        """
        Report params a call site passes that no include it reached mentions:
        a call named by ``$PARAM`` passes what any of its targets needs.
        """
        for src, (targets, passed) in self.calls.items():
            known = set().union(*(self.params[name] for name in targets))
            for param in passed - known:
                names = "/".join(sorted(targets))
                self.report("unknown-param", src, f"{names}: no param {param!r}")

    def check_ids(self, window: str, root: Node) -> None:
        """
        Expand includes into a copy of ``window`` and collect control ids used
        twice where both can load (divergent include conditions are skipped).

        :param window: Window file name.
        :param root: Parsed window.
        """
        root = clone(root)
        self.expand(root, budget=[100_000])
        seen = defaultdict(list)
        for control, branch in controls(root):
            seen[control.get("id")].append((control.src, branch))
        for cid, hits in seen.items():
            clashing = sorted(
                src
                for i, (src, branch) in enumerate(hits)
                if any(
                    not exclusive(branch, other)
                    for j, (_, other) in enumerate(hits)
                    if i != j
                )
            )
            if clashing:
                self.duplicates[cid, tuple(clashing)].append(window)

    def expand(self, node: Node, budget: list[int]) -> None:
        """
        Resolve includes under ``node`` in place like ``ResolveIncludes``:
        ``<nested/>`` filled, params substituted, constant-false conditions
        skipped, other conditions recorded, not evaluated.

        :param node: Element whose include children are replaced.
        :param budget: Remaining expansions, shared to stop include recursion.
        """
        index = 0
        while index < len(node):
            call = node[index]
            name = include_name(call) if call.tag == "include" else None
            if name is not None and self.constant_false(call.get("condition", "")):
                del node[index]  # Kodi skips it before looking the name up
                continue
            if name not in self.defs["include"] or "file" in call.attrib:
                if name is not None and "file" not in call.attrib:
                    self.report("undefined-include", call.src, name or "(no name)")
                index += 1
                continue
            self.record_call(call, name)
            budget[0] -= 1
            if budget[0] < 0:
                self.report("include-recursion", call.src, name)
                return
            params = self.defaults[name] | params_of(call, "value")
            payload = [c for c in elements(call) if c.tag != "param"]
            condition = call.get("condition")
            branch = call.branch + ((f"{call.src} {condition}",) if condition else ())
            inserted, resolve = [], []
            for child in elements(self.body(name)):
                new = clone(child)
                if new.tag == "nested":
                    inserted += map(clone, payload)
                elif (nested := new.find("nested")) is not None:
                    at = list(new).index(nested)
                    new[at : at + 1] = [clone(c) for c in payload]
                inserted.append(new)
                resolve.append(new)
            for new in inserted:
                new.branch = branch
            node[index : index + 1] = inserted
            for new in resolve:
                self.resolve_params(new, params, node)
        for child in elements(node):
            self.expand(child, budget)

    def constant_false(self, condition: str) -> bool:
        """
        True for ``false``, ``!true`` or a bare ``$EXP`` chain whose generated body
        is ``false``: Kodi evaluates an include condition at load and skips it.

        :param condition: Include condition after param substitution.
        :return: Whether Kodi never loads the include.
        """
        seen = set()
        while match := WHOLE_EXP.fullmatch(condition.strip()):
            name = match[1]
            if name in seen or name not in self.defs["expression"]:
                return False
            seen.add(name)
            condition = (self.defs["expression"][name].text or "").strip()
        return condition.lower() in ("false", "!true")

    def resolve_params(self, node: Node, params: dict[str, str], parent: Node) -> None:
        """
        Substitute ``$PARAM[...]`` like ``ResolveParametersForNode``, checking
        references built from params and dropping forwarded undefined params.

        :param node: Element to resolve in place.
        :param params: Call-site values over definition defaults.
        :param parent: Parent of ``node``, for the drop.
        """

        def lookup(match: re.Match) -> str:
            return params.get(match[1], "")

        def substitute(value: str) -> str | None:
            whole = PARAM.fullmatch(value)
            if whole and whole[1] not in params and node.tag == "param":
                return None
            for token, name in REF.findall(value):
                if "$PARAM[" in name:
                    self.check_reference(token, PARAM.sub(lookup, name), node.src)
            return PARAM.sub(lookup, value)

        forwarded = parent.tag == "include"
        for key, value in node.attrib.items():
            new = substitute(value)
            if new is None and key == "value" and forwarded:
                parent.remove(node)
                return
            node.set(key, new or "")
        if (node.text or "").strip():
            new = substitute(node.text)
            if new is None and forwarded:
                parent.remove(node)
            else:
                node.text = new or ""
            return
        for child in elements(node):
            self.resolve_params(child, params, node)

    def migrated(self) -> list[str]:
        """Window files that call a C2 shell include (``C2_SHELLS``)."""
        return [
            name
            for name, root in self.roots.items()
            if root.tag == "window"
            and any(include_name(c).startswith(C2_SHELLS) for c in root.iter("include"))
        ]

    def check_window(self, name: str) -> None:
        """
        Check what Kodi resolves when window ``name`` loads: its includes expanded,
        then every ``$VAR``/``$EXP`` reachable from it or its include conditions.
        """
        root = clone(self.roots[name])
        self.check_calls(root)
        self.expand(root, budget=[100_000])
        queue = [root]
        for branch in {b for node in root.iter() for b in getattr(node, "branch", ())}:
            src, _, condition = branch.partition(" ")
            queue.append(Node("include", {"condition": condition}))
            queue[-1].src = src
        while queue:
            for node, value in values(queue.pop()):
                for token, ref in REF.findall(value):
                    self.check_reference(token, ref, node.src)
                    kind, ref = KINDS[token], ref.split(",")[0]
                    if (kind, ref) not in self.reached and ref in self.defs[kind]:
                        self.reached.add((kind, ref))
                        queue.append(self.defs[kind][ref])
        self.check_ids(name, self.roots[name])

    def check_unreferenced(self) -> None:
        """
        Report generated variables and expressions that no linted window reaches,
        through its values or its include conditions.
        """
        for kind in KINDS.values():
            for name, node in self.defs[kind].items():
                if (
                    node.src.startswith(GENERATED)
                    and not name.endswith(UNMIGRATED)
                    and (kind, name) not in self.reached
                ):
                    self.report("unreferenced-definition", node.src, f"{kind} {name}")

    def lint(self, windows: list[str] | None = None) -> set[Finding]:
        """
        Run every rule over the given windows, or over every loaded file.

        :param windows: Window file names; ``None`` lints the whole skin.
        :return: All findings.
        """
        for name, root in self.roots.items():
            if windows is not None:
                if name in windows:
                    self.check_window(name)
                continue
            if root.tag == "includes" and name not in self.loaded:
                continue
            self.check_references(root)
            self.check_calls(root)
            if root.tag == "window":
                self.check_ids(name, root)
        if windows is not None:
            self.check_unreferenced()
        self.check_params()
        for (cid, srcs), windows in self.duplicates.items():
            where = ", ".join(
                f"{src} ×{n}" if n > 1 else src for src, n in Counter(srcs).items()
            )
            shown = ", ".join(windows[:3]) + (", …" if len(windows) > 3 else "")
            self.report("duplicate-id", srcs[0], f"id {cid}: {where} [{shown}]")
        return self.findings


def location(finding: Finding) -> tuple[str, int]:
    """Sort key: file name, then numeric line."""
    file, _, line = finding.src.rpartition(":")
    return file, int(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("skin", type=Path, help="skin root directory")
    parser.add_argument("--generated", type=Path, help="existing build_offline output")
    parser.add_argument(
        "--exclude", action="append", default=[], help="hide findings in files (glob)"
    )
    parser.add_argument(
        "--all", action="store_true", help="lint every file, not just C2 windows"
    )
    parser.add_argument(
        "--window", action="append", default=[], help="also lint this window file"
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as name:
        generated = args.generated
        if not generated:
            generated = Path(name)
            print(f"build: {build_isolated(args.skin, generated)}")
        files = {p.name: p for p in sorted((args.skin / "16x9").glob("*.xml"))}
        files |= {p.name: p for p in sorted((generated / "16x9").glob("*.xml"))}
        skin = Skin(list(files.values()))
        windows = None if args.all else sorted({*skin.migrated(), *args.window})
        if windows:
            print(f"windows: {', '.join(windows)}")
        findings = skin.lint(windows)

    shown = [
        f
        for f in findings
        if not any(fnmatch(location(f)[0], glob) for glob in args.exclude)
    ]
    by_rule = defaultdict(list)
    for finding in sorted(shown, key=location):
        by_rule[finding.rule].append(finding)
    for rule, group in sorted(by_rule.items()):
        print(f"\n== {rule} ({'error' if rule in ERRORS else 'warning'}, {len(group)})")
        for finding in group:
            print(f"  {finding.src}  {finding.message}")
    errors = sum(f.rule in ERRORS for f in shown)
    hidden = f", {len(findings) - len(shown)} excluded" if args.exclude else ""
    print(f"\n{errors} errors, {len(shown) - errors} warnings{hidden}")
    sys.exit(bool(errors))


if __name__ == "__main__":
    main()
