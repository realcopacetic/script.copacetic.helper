"""
Lint a skin's ``16x9/*.xml`` together with freshly generated helper outputs.

Mirrors Omega's ``CGUIIncludes`` load and resolve rules. By default only what
the migrated (C2) windows load is checked; ``--all``, or a skin with none (C1),
checks everything. Also checks that ``media`` textures store white under fully
transparent pixels. Errors exit 1.
"""

import argparse
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from fnmatch import fnmatch
from itertools import chain
from pathlib import Path
from typing import Iterator, NamedTuple
from xml.parsers import expat

from build_offline import build_isolated
from PIL import Image, ImageChops, ImageSequence

REF = re.compile(r"\$(?:ESC(?=VAR))?(VAR|EXP)\[((?:[^\[\]]|\[[^\[\]]*\])+)\]")
ESCEXP = re.compile(r"\$ESCEXP\[(?:[^\[\]]|\[[^\[\]]*\])+\]")  # not a Kodi token
PARAM = re.compile(r"\$PARAM\[([^\[\]]*)\]")
FIELD = re.compile(r"\{[^{}]*\}")  # a builder placeholder: {layout}, {index+1}
WHOLE_EXP = re.compile(r"\[?\$EXP\[([^\[\]]+)\]\]?")
INCLUDE_REF = re.compile(r"\$(?:EXP|PARAM)\[[^\[\]]*\]")  # resolved by includes only
CONDITION_REF = re.compile(r"\$(?:EXP|PARAM|(?:ESC)?VAR)\[[^\[\]]*\]")
TIMER_CONDITIONS = {"start", "reset", "stop"}
TIMER_ACTIONS = {"onstart", "onstop"}
TIMER_IGNORED = {"include", "constant"}  # CGUIIncludes elements
KINDS = {"VAR": "variable", "EXP": "expression"}
DEFINITIONS = ("include", "expression", "variable")
LAYOUTS = {"itemlayout", "focusedlayout"}
NUMBER = re.compile(r"\s*[-+]?\.?\d")  # the prefix sscanf's %f needs
BUDGET = 1_000_000  # include expansions per window; C1 master's Home.xml took ~580,000
GENERATED = "script-copacetic-helper_"
UNMIGRATED = ("_addonbrowser", "_pictures")  # pre-built for windows not yet migrated
C2_SHELLS = (
    *("tpl_window", "blk_modal_", "tpl_modal_", "img_modal_", "blk_hud_"),
    *("tpl_editor", "blk_settings_panels"),  # the editors and the settings windows
    "blk_osd_",  # VideoOSD and the seek bar and info dialogs over fullscreen video
)
MEDIA_WINDOWS = {  # CGUIMediaWindow subclasses: the only windows GetMediaWindow returns
    *("AddonBrowser.xml", "EventLog.xml", "MyFavourites.xml", "MyGames.xml"),
    *("MyMusicNav.xml", "MyMusicPlaylistEditor.xml", "MyPics.xml", "MyPlaylist.xml"),
    *("MyPrograms.xml", "MyPVRChannels.xml", "MyPVRGuide.xml", "MyPVRRecordings.xml"),
    *("MyPVRSearch.xml", "MyPVRTimers.xml", "MyVideoNav.xml"),
}
OPAQUE = re.compile(r"\$\w+\[[^\[\]]*\]")  # $INFO[…], $VAR[…]: one unknown operand
# operators, and the operands between them trimmed as CGUIInfoManager::Register does
TOKEN = re.compile(r"[!+|\[\]]|[^!+|\[\]\s](?:[^!+|\[\]]*[^!+|\[\]\s])?")
BINARY = (("|", max), ("+", min))  # loosest first; Kleene logic over 0, 0.5, 1
MEDIA_INFO = re.compile(  # label forms with no id; Row/Column/Position(n) are bools
    r"(?<![\w.])Container(?:\(\s*0?\s*\))?\."
    r"(?:NumItems|CurrentItem|NumPages|CurrentPage|NumAllItems|NumNonFolderItems"
    r"|Position|Row|Column)\b(?!\()",
    re.IGNORECASE,
)
EMPTY_ID = re.compile(r"(?<![\w.])Container\(\s*\)", re.I)  # a $PARAM id left empty
ERRORS = {
    "parse",
    "empty-definition",
    "escaped-expression",
    "include-recursion",
    "undefined-expression",
    "undefined-include",
    "undefined-variable",
    "texture-clear",
    "timer-unresolved",
}


class Node(ET.Element):
    """
    Element that remembers where it was parsed, which conditions load it and,
    once inserted, the include calls expanded above it.
    """

    src = "?:0"
    branch = ()
    stack = None


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
    """Deep copy keeping ``src`` and ``stack`` (``deepcopy`` drops the subclass)."""
    if not isinstance(node.tag, str):
        return ET.Comment(node.text)
    new = Node(node.tag, dict(node.attrib))
    new.text, new.tail, new.src, new.stack = node.text, node.tail, node.src, node.stack
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
    """True when two include-condition paths diverge, so they never load together."""
    return a[: len(b)] != b[: len(a)]


def fold(condition: str) -> bool | None:
    """
    Constant value of a bool ``condition``, or ``None`` when an info decides it:
    ``!`` binds tightest, then ``+``, then ``|``, and ``[]`` group, as Kodi parses.

    :param condition: Bool expression; ``$INFO[…]``-style references are unknown.
    :return: ``True`` or ``False`` when constant, else ``None``.
    """
    text = condition.lower()
    while (opaque := OPAQUE.sub("?", text)) != text:
        text = opaque
    tokens = TOKEN.findall(text)[::-1]

    def parse(level: int = 0) -> float:
        if level == len(BINARY):
            token = tokens.pop() if tokens else ""
            if token == "!":
                return 1 - parse(level)
            if token != "[":
                return {"true": 1, "yes": 1, "false": 0, "no": 0}.get(token, 0.5)
            value = parse()
            if tokens[-1:] == ["]"]:
                tokens.pop()
            return value
        op, join = BINARY[level]
        value = parse(level + 1)
        while tokens[-1:] == [op]:
            tokens.pop()
            value = join(value, parse(level + 1))
        return value

    value = parse()
    return None if tokens or value == 0.5 else bool(value)


def dead(condition: str) -> bool:
    """True when ``condition`` is false whatever its infos, e.g. ``[false] + a``."""
    return fold(condition) is False


def timer_reads(root: Node) -> Iterator[tuple[Node, str, str]]:
    """
    Yield ``(element, condition, action text)`` for what ``LoadTimerInternal`` reads:
    the first ``<start>``, ``<reset>``, ``<stop>`` and every ``<onstart>``/``<onstop>``
    of each ``<timer>`` with a ``<name>`` no earlier timer took.
    """
    seen = set()
    for timer in root.iterfind("timer"):
        name = timer.findtext("name")
        if not name or name in seen:
            continue
        seen.add(name)
        for tag in TIMER_CONDITIONS:
            if (node := timer.find(tag)) is not None:
                yield node, node.text or "", ""
        for tag in TIMER_ACTIONS:
            for node in timer.iterfind(tag):
                yield node, node.get("condition", ""), node.text or ""


def first_three(names: list[str]) -> str:
    """Join up to three names, with an ellipsis when there are more."""
    return ", ".join(names[:3]) + (", …" if len(names) > 3 else "")


class Skin:
    """Parsed skin files plus the definitions Kodi would register from them."""

    def __init__(
        self,
        paths: list[Path],
        media_families: tuple[str, ...],
        window_families: tuple[str, ...] = (),
        filled: frozenset[tuple[str, str]] = frozenset(),
    ):
        """
        Parse every file, then register definitions from the include files
        ``Includes.xml`` loads, in load order.

        :param paths: XML files to lint.
        :param media_families: Name suffixes of the builder's media window definitions.
        :param window_families: Name suffixes of every builder window and scope.
        :param filled: ``(include glob, param)`` pairs templates fill per mapping row.
        """
        self.findings = set()
        self.media_families = media_families
        self.window_families = window_families
        self.filled = filled
        self.roots = {}
        for path in paths:
            try:
                self.roots[path.name] = parse(path)
            except expat.ExpatError as e:
                self.report("parse", f"{path.name}:{e.lineno}", str(e))
        self.defs = {kind: {} for kind in DEFINITIONS}
        self.defaults = {}
        self.types = {}
        self.constants = {}
        self.params = {}
        self.calls = defaultdict(lambda: (set(), set()))
        self.duplicates = defaultdict(list)
        self.reached = set()
        self.media_info = defaultdict(set)
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
        for node in self.roots[name].iterfind("constant"):  # before any included file
            if node.get("name") and node.text:
                self.constants.setdefault(node.get("name"), node.text)
        for node in elements(self.roots[name]):
            if node.tag == "include" and "file" in node.attrib:
                self._load(node.get("file"), node.src)
            elif node.tag in DEFINITIONS and node.get("name"):
                self._register(node)
            elif node.tag == "default" and node.get("type") and len(node):
                self.types.setdefault(node.get("type"), node)  # first one wins

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
                for call in node.iter("include"):  # $PARAM-named: reaches its default
                    whole = PARAM.fullmatch(include_name(call))
                    if whole and (default := self.defaults[name].get(whole[1])):
                        self.calls[call.src][0].add(default)

    def body(self, name: str) -> Node:
        """Included part of an include definition."""
        node = self.defs["include"][name]
        definition = node.find("definition")
        return node if definition is None else definition

    def check_reference(
        self, token: str, name: str, src: str, call: Node | None = None
    ) -> None:
        """
        Report a ``$VAR``/``$EXP`` with no definition; ``$PARAM`` names skip,
        as does a param value the expansion of include ``call`` drops.
        """
        kind = KINDS[token]
        if kind == "variable":
            name = name.split(",")[0]
        if (
            "$" in name
            or name in self.defs[kind]
            or self.dropped(call, f"${token}[{name}")
        ):
            return
        self.report(f"undefined-{kind}", src, f"${token}[{name}]")

    def check_references(self, root: Node) -> None:
        """Check every literal ``$VAR``/``$EXP``/``$ESCEXP`` token in ``root``."""
        calls = {
            param: call
            for call in root.iter("include")
            if "content" in call.attrib
            for param in call.iterfind("param")
        }
        for node, value in values(root):
            self.check_escexp(node.src, value)
            for token, name in REF.findall(value):
                self.check_reference(token, name, node.src, calls.get(node))

    def dropped(self, call: Node | None, ref: str) -> bool:
        """
        True when expanding include ``call`` alone leaves ``ref`` nowhere: the param
        reaches only includes Kodi skips, so Kodi never reads it.
        """
        if call is None:
            return False
        holder = Node("holder")
        holder.append(clone(call))
        kept = self.findings, self.calls  # a trial expansion records nothing
        self.findings, self.calls = set(), defaultdict(lambda: (set(), set()))
        self.expand(holder, budget=[BUDGET])
        self.findings, self.calls = kept
        branches = (b for node in holder.iter() for b in getattr(node, "branch", ()))
        texts = chain((value for _, value in values(holder)), branches)
        return not any(ref in text for text in texts)

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
        a call named by ``$PARAM`` passes what any of its targets or its default needs,
        and a generated call passes its mapping row's fields to whichever it picks.
        """
        for src, (targets, passed) in self.calls.items():
            known = set().union(*(self.params.get(name, ()) for name in targets))
            if src.startswith(GENERATED):
                known.update(
                    param
                    for glob, param in self.filled
                    if any(fnmatch(name, glob) for name in targets)
                )
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
        self.expand(root, budget=[BUDGET])
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

    def expand(
        self,
        node: Node,
        budget: list[int],
        keep: bool = False,
        path: tuple = (),
        depth: int = 0,
    ) -> None:
        """
        Resolve includes under ``node`` in place like ``ResolveIncludes``:
        ``<nested/>`` filled, params substituted, constant-false conditions
        skipped, other conditions recorded, not evaluated.

        :param node: Element whose include children are replaced.
        :param budget: Remaining expansions, shared to stop include blow-up.
        :param keep: Keep skipped calls, as Kodi does, skipping all constant-false ones.
        :param path: Include calls (name, params) above ``node``; a repeat recurses.
        :param depth: Elements above ``node``, capped below Python's recursion limit.
        """
        skipped = self.never if keep else self.constant_false
        index = 0
        while index < len(node):
            call = node[index]
            name = include_name(call) if call.tag == "include" else None
            if name is not None and skipped(call.get("condition", "")):
                if keep:
                    index += 1  # Kodi steps past it; its payload is still resolved
                else:
                    del node[index]  # Kodi skips it before looking the name up
                continue
            if name not in self.defs["include"] or "file" in call.attrib:
                if name is not None and "file" not in call.attrib:
                    self.report("undefined-include", call.src, name or "(no name)")
                index += 1
                continue
            self.record_call(call, name)
            params = self.defaults[name] | params_of(call, "value")
            key = name, frozenset(params.items())  # same call again: never ends
            outer = path if call.stack is None else call.stack
            # or a param that grows each call: too many calls, or too deep to expand
            if key in outer or len(outer) > 200 or depth > 400:
                self.report("include-recursion", call.src, name)
                del node[index]
                continue
            budget[0] -= 1
            if budget[0] < 0:
                self.report("include-recursion", call.src, name)
                return
            payload = [c for c in elements(call) if c.tag != "param"]
            for element in payload:
                element.stack = outer  # the caller's, not the include's
            condition = call.get("condition")
            branch = call.branch + ((f"{call.src} {condition}",) if condition else ())
            inserted, resolve, inner = [], [], (*outer, key)
            for child in elements(self.body(name)):
                new = clone(child)
                new.stack = inner
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
            stack = path if child.stack is None else child.stack
            self.expand(child, budget, keep, stack, depth + 1)

    def constant_false(self, condition: str) -> bool:
        """
        True when ``condition``, or the body a bare ``$EXP`` chain ends at, is false
        whatever its infos: Kodi evaluates an include condition at load and skips it.

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
        return fold(condition) is False

    def never(self, condition: str) -> bool:
        """
        True when ``condition`` is false once flattened, whatever its infos, so
        ``ResolveIncludes`` always skips the call.

        :param condition: Include condition after param substitution.
        :return: Whether Kodi never loads the include.
        """
        return fold(self.flatten(condition)) is False

    def set_defaults(self, control: Node) -> list[Node]:
        """
        Tags ``SetDefaults`` appends to ``control``: its type's ``<default>`` children.

        :param control: Expanded ``<control>`` element.
        :return: Default tags appended, in order.
        """
        default = self.types.get(control.get("type", ""))
        return [] if default is None else elements(default)

    def flatten(self, condition: str, seen: tuple[str, ...] = ()) -> str:
        """
        Replace each ``$EXP[name]`` with its ``[body]``, flattened, as Omega's
        ``ResolveExpressions`` does; unknown or circular names become empty.

        :param condition: Include condition after param substitution.
        :param seen: Expression names being flattened, for the circular check.
        :return: The text Kodi registers.
        """

        def body(match: re.Match) -> str:
            name = match[2]
            if match[1] == "VAR":
                return match[0]
            if name in seen or name not in self.defs["expression"]:
                return ""
            text = self.defs["expression"][name].text or ""
            return f"[{self.flatten(text, (*seen, name))}]"

        return REF.sub(body, condition)

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

    def count(self, name: str) -> str:
        """
        Size what ``CGUIWindow::Prepare`` builds for window ``name``: the expanded
        tree with skipped includes left in place and control defaults added, and the
        non-constant include conditions Kodi records (one changing reloads it).

        :param name: Window file name.
        :return: One summary line.
        """
        root = clone(self.roots[name])
        self.expand(root, budget=[BUDGET], keep=True)
        nodes = [e for e in root.iter() if isinstance(e.tag, str)]
        dead = [
            e
            for e in nodes
            if e.tag == "include" and self.never(e.get("condition", ""))
        ]
        carried = {c for e in dead for c in e.iter() if isinstance(c.tag, str)}
        ctrls = [e for e in nodes if e.tag == "control"]
        added = [c for e in ctrls for tag in self.set_defaults(e) for c in tag.iter()]
        size = len(nodes) + sum(isinstance(c.tag, str) for c in added)
        branches = {b.partition(" ")[2] for e in nodes for b in e.branch}
        conditions = {self.flatten(c).strip().lower() for c in branches}
        live = sum(fold(c) is None for c in conditions if c)
        return (
            f"{name}: {size} elements, {len(ctrls)} controls, "
            f"{len(dead)} skipped includes carrying {len(carried - {*dead})} elements, "
            f"{live} live include conditions"
        )

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
        self.expand(root, budget=[BUDGET])
        live = name not in MEDIA_WINDOWS
        queue, reached = [(root, live)], {}
        for branch in {b for node in root.iter() for b in getattr(node, "branch", ())}:
            src, _, condition = branch.partition(" ")
            include = Node("include", {"condition": condition})
            include.src = src
            queue.append((include, live))
        while queue:
            top, live = queue.pop()
            for node, value in values(top):
                live_here = live and not dead(value)
                if live_here:
                    self.check_media_info(node.src, value, name)
                    if EMPTY_ID.search(value):
                        message = "Container() reads the focused control here"
                        self.report("empty-container-id", node.src, message)
                self.check_escexp(node.src, value)
                for token, ref in REF.findall(value):
                    self.check_reference(token, ref, node.src)
                    kind, ref = KINDS[token], ref.split(",")[0]
                    if ref not in self.defs[kind]:
                        continue
                    definition = self.defs[kind][ref]
                    live_ref = live_here and not (
                        node.src.startswith(GENERATED)
                        and definition.src.startswith(GENERATED)
                        and ref.endswith(self.media_families)
                    )
                    if (kind, ref) not in reached or live_ref > reached[kind, ref]:
                        reached[kind, ref] = live_ref
                        queue.append((definition, live_ref))
        self.reached |= reached.keys()
        self.check_times(root)
        self.check_ids(name, self.roots[name])

    def check_times(self, root: Node) -> None:
        """
        Report animation ``time``/``delay`` values that are no number once
        ``ResolveConstant`` has swapped in constants: Kodi drops them silently.
        """
        timed = (  # CAnimation::Create: an animation's own only when it has no <effect>
            e
            for e in root.iter()
            if e.tag == "effect" or e.tag == "animation" and e.find("effect") is None
        )
        for node in timed:
            for key in ("time", "delay"):
                value = node.get(key, "")
                if value and not NUMBER.match(self.constants.get(value, value)):
                    self.report("undefined-constant", node.src, f'{key}="{value}"')

    def check_escexp(self, src: str, value: str) -> None:
        """Report ``$ESCEXP[…]`` in ``value``, which Kodi leaves literal."""
        for token in ESCEXP.findall(value):
            self.report("escaped-expression", src, f"{token} stays literal")

    def check_media_info(self, src: str, value: str, context: str) -> None:
        """
        Record label-form container infos with no id in ``value``: they read only a
        media window's view, so in ``context`` (not a media window) they are empty.

        :param src: Where ``value`` was parsed.
        :param value: Text or attribute value.
        :param context: Non-media window or ``Timers.xml`` that reaches it.
        """
        for info in MEDIA_INFO.findall(value):
            self.media_info[src, info].add(context)

    def check_timers(self, root: Node) -> None:
        """
        Check what Kodi reads in ``Timers.xml`` for media infos and for references it
        leaves literal: it skips includes, so ``<include>``, ``<constant>``, ``$EXP``
        and ``$PARAM`` anywhere; ``$VAR`` everywhere but action text (checked defined).

        :param root: Parsed ``Timers.xml``.
        """
        for node in root.iter():
            if node.tag in TIMER_IGNORED:
                name = node.get("name") or include_name(node)
                self.report(
                    "timer-unresolved", node.src, f"<{node.tag}> {name} is ignored"
                )
        for node, condition, action in timer_reads(root):
            for value in (condition, action):
                self.check_media_info(node.src, value, "Timers.xml")
                self.check_escexp(node.src, value)
            for ref in CONDITION_REF.findall(condition) + INCLUDE_REF.findall(action):
                self.report("timer-unresolved", node.src, f"{ref} stays literal")
            for token, ref in REF.findall(action):  # $VAR resolves when the action runs
                if token == "VAR":
                    self.check_reference(token, ref, node.src)

    def family(self, kind: str, name: str) -> tuple[str, str] | None:
        """``(kind, name less its suffix)`` for a per-window or per-scope definition."""
        suffix = next((s for s in self.window_families if name.endswith(s)), None)
        return suffix and (kind, name.removesuffix(suffix))

    def check_unreferenced(self) -> None:
        """
        Report generated variables and expressions that no linted window reaches,
        through its values or include conditions, unless another window's (or scope's)
        copy is reached: the builder writes one for each, mounted reader or not.
        """
        mounted = {self.family(*key) for key in self.reached} - {None}
        for kind in KINDS.values():
            for name, node in self.defs[kind].items():
                if (
                    node.src.startswith(GENERATED)
                    and not name.endswith(UNMIGRATED)
                    and (kind, name) not in self.reached
                    and self.family(kind, name) not in mounted
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
            if name == "Timers.xml":  # check_timers reads only what Kodi reads
                continue
            if root.tag == "includes" and name not in self.loaded:
                continue
            self.check_references(root)
            self.check_calls(root)
            if root.tag == "window":
                self.check_ids(name, root)
        if windows is not None:
            self.check_unreferenced()
        if "Timers.xml" in self.roots:
            self.check_timers(self.roots["Timers.xml"])
        for (src, info), contexts in self.media_info.items():
            where = first_three(sorted(contexts))
            message = (
                f"{info} with no id reads only the active media window: empty on Home"
                f" and search, and in dialogs over them [{where}]"
            )
            self.report("media-window-info", src, message)
        self.check_params()
        for (cid, srcs), windows in self.duplicates.items():
            where = ", ".join(
                f"{src} ×{n}" if n > 1 else src for src, n in Counter(srcs).items()
            )
            shown = first_three(windows)
            self.report("duplicate-id", srcs[0], f"id {cid}: {where} [{shown}]")
        return self.findings


def check_textures(skin: Path) -> Iterator[Finding]:
    """
    Report textures with a colour other than white under fully transparent pixels;
    Kodi samples them with ``GL_LINEAR``, which blends it into the visible edge.

    :param skin: Skin root directory.
    :return: One finding per texture, naming its first offending frame.
    """
    for path in sorted((skin / "media").rglob("*.*png")):
        for n, frame in enumerate(ImageSequence.Iterator(Image.open(path))):
            r, g, b, a = frame.convert("RGBA").split()
            darkest = ImageChops.darker(ImageChops.darker(r, g), b)
            visible = a.point(lambda v: v and 255)
            if ImageChops.lighter(darkest, visible).getextrema()[0] < 255:
                frame_no = f" (frame {n})" if n else ""
                message = f"not white under transparent pixels{frame_no}"
                yield Finding("texture-clear", f"{path.relative_to(skin)}:0", message)
                break


def window_metadata(skin: Path) -> dict[str, dict[str, str]]:
    """
    Builder windows and their metadata, from ``mappings_windows.json``.

    :param skin: Skin root directory.
    :return: {window: metadata}; empty if the skin has no mappings (C1).
    """
    path = skin / "extras/templates/mappings/mappings_windows.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())["windows"]["metadata"]


def media_families(skin: Path) -> tuple[str, ...]:
    """
    Name suffixes of the generated per-window definitions of the builder's media
    windows: the ``mappings_windows.json`` windows with ``mode`` ``media``.

    :param skin: Skin root directory.
    :return: Suffixes such as ``_videos``; none if the skin has no mappings (C1).
    """
    return tuple(
        f"_{w}" for w, meta in window_metadata(skin).items() if meta["mode"] == "media"
    )


def window_families(skin: Path) -> tuple[str, ...]:
    """
    Name suffixes of the generated per-window and per-scope definitions: one for each
    ``mappings_windows.json`` window and each ``scope`` they name.

    :param skin: Skin root directory.
    :return: Suffixes such as ``_home``, ``_widgets``; none without mappings (C1).
    """
    names = {
        name for w, meta in window_metadata(skin).items() for name in (w, meta["scope"])
    }
    return tuple(f"_{name}" for name in sorted(names))


def filled_params(skin: Path) -> frozenset[tuple[str, str]]:
    """
    Params the include templates fill per mapping row (a ``{field}`` in the value),
    with the call's name as a glob: a placeholder or ``$PARAM`` in it matches anything.

    :param skin: Skin root directory.
    :return: ``(include glob, param)`` pairs; none if the skin has no templates (C1).
    """
    calls = (
        call
        for path in (skin / "extras/templates/includes").glob("*.xml")
        for call in ET.parse(path).iter("include")
        if "content" in call.attrib
    )
    return frozenset(
        (FIELD.sub("*", PARAM.sub("*", call.get("content"))), param.get("name"))
        for call in calls
        for param in call.iterfind("param")
        if FIELD.search(param.get("value", param.text or ""))
    )


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
    parser.add_argument(
        "--count", action="store_true", help="size each window's prepared tree"
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as name:
        generated = args.generated
        if not generated:
            generated = Path(name)
            print(f"build: {build_isolated(args.skin, generated)}")
        files = {p.name: p for p in sorted((args.skin / "16x9").glob("*.xml"))}
        files |= {p.name: p for p in sorted((generated / "16x9").glob("*.xml"))}
        skin = Skin(
            list(files.values()),
            media_families(args.skin),
            window_families(args.skin),
            filled_params(args.skin),
        )
        windows = None if args.all else sorted({*skin.migrated(), *args.window}) or None
        if windows:
            print(f"windows: {', '.join(windows)}")
        findings = skin.lint(windows) | set(check_textures(args.skin))
        if args.count:  # after lint: expanding again records calls and findings
            for window in windows or sorted(skin.roots):
                if skin.roots[window].tag == "window":
                    print(skin.count(window))

    shown = [
        f
        for f in findings
        if not any(fnmatch(location(f)[0], glob) for glob in args.exclude)
    ]
    by_rule = defaultdict(list)
    for finding in sorted(shown, key=lambda f: (location(f), f.message)):
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
