# author: realcopacetic

import math
from typing import Any, Callable, Collection, Iterable, Mapping

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.geometry import (
    PlacementOpts,
    align_x,
    align_y,
    axis_travel,
    compute_rect,
)
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    return_label,
    split,
    split_random,
    to_int,
    url_encode,
    xbmc,
)


def has_value(value: Any) -> bool:
    """Whether a value should be preserved and not overwritten."""
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, dict)):
        return bool(value)
    return True  # ints, bools, floats: treat all as meaningful


def merge_metadata(
    base: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    prefer_incoming: bool = False,
    ignore_keys: Collection[str] = ("art", "file"),
) -> dict[str, Any]:
    """Merge incoming metadata into a base metadata dict.

    Mutates ``base`` in place using has_value rules and overwrite policy.
    :param base: Local metadata dict to update in place.
    :param incoming: Metadata dict to merge values from.
    :param prefer_incoming: If true, prefer incoming over non-empty base.
    :param ignore_keys: Top-level keys to skip entirely when merging.
    :return: Updated base metadata dict.
    """
    incoming_props = incoming.get("properties")
    if isinstance(incoming_props, Mapping):
        local_props = base.setdefault("properties", {})
        for key, incoming_val in incoming_props.items():
            local_val = local_props.get(key)
            if prefer_incoming:
                if has_value(incoming_val):
                    local_props[key] = incoming_val
            else:
                if not has_value(local_val) and has_value(incoming_val):
                    local_props[key] = incoming_val

    for key, incoming_val in incoming.items():
        if key == "properties" or key in ignore_keys:
            continue

        local_val = base.get(key)
        if prefer_incoming:
            if has_value(incoming_val):
                base[key] = incoming_val
        else:
            if not has_value(local_val) and has_value(incoming_val):
                base[key] = incoming_val

    return base


def get_infolabels(target: str, keys: Iterable[str]) -> dict[str, str]:
    """
    Fetch multiple infolabels for the targeted listitem.

    :param target: Container/listitem prefix indicating where to read from.
    :param keys: Iterable of infolabel suffixes.
    :return: Dict mapping suffix → value.
    """
    return {key: infolabel(f"{target}.{key}") for key in keys}


class DataHandler:
    """Extracts metadata for a Kodi ListItem and prepares a normalized dict."""

    def __init__(
        self,
        target: str,
        dbtype: str,
        dbid: str,
    ) -> None:
        """
        Initialize the handler with listitem, dbtype and dbid.

        :param target: InfoLabel prefix (e.g. "Container(3100).ListItem").
        :param dbtype: Database content type (e.g. video or tvshow).
        :param dbid: Database ID for the given item.
        """
        self.target = target
        self.dbtype = dbtype
        self.dbid = dbid
        self.infolabels = get_infolabels(
            self.target,
            [
                "Label",
                "Director",
                "Writer",
                "Genre",
                "Studio",
            ],
        )

    def fetch_data(self) -> dict[str, object]:
        """
        Build a normalized metadata dictionary.

        :return: Dictionary with art, resume, contributors, etc.
        """
        label = return_label(self.infolabels["Label"])
        encoded_label = url_encode(label)
        return {
            "file": encoded_label,
            "label": label,
            "label2": label,
            "Directors": split_random(self.infolabels["Director"]),
            "Genres": split_random(self.infolabels["Genre"]),
            "Studios": self._studio(),
            "Writers": split(self.infolabels["Writer"]),
        }

    def _studio(self) -> str:
        """
        Returns first studio name, cleaned of '+'.

        :return: Studio string or empty string.
        """
        studio = (
            split(infolabel(f"{self.target}(-1).Studio"))
            if "set" in self.dbtype
            else split(self.infolabels["Studio"])
        )
        return studio.replace("+", "") if studio else ""


class JumpButton:
    """
    Scrollbar thumb indicator with optional sort letter.
    Positioning is fully driven by compute_rect + PlacementOpts.
    """

    def __init__(
        self, scroll_id: int = 60, btn_id: int = 62, btn_width: int = 30
    ) -> None:
        """
        Initializes the control IDs used for the scrollbar and indicator button.

        :param scroll_id: Scrollbar control ID to read "cur/total" from.
        :param btn_id: Indicator button control ID to position.
        :param btn_width: Fallback button width/height when control returns 0.
        """
        self.window = Window(getCurrentWindowId())
        self.scroll_id = scroll_id
        self.btn_id = btn_id
        self.btn_width = btn_width

    def _fraction_from_scrollbar(self, scroll_id: int) -> float:
        """
        Compute a 0..1 fraction from Control.GetLabel(scroll_id) formatted as "cur/total".

        :param scroll_id: Scrollbar control ID.
        :return: Fractional position in range [0.0, 1.0], or 0.0 if invalid.
        """
        raw = infolabel(f"Control.GetLabel({scroll_id})").strip()
        if not raw or "/" not in raw:
            return 0
        try:
            cur, total = map(int, raw.split("/"))
            return (cur / total) if total else 0
        except Exception:
            return 0

    def update(
        self, *, sortletter: str | None, scroll_id: int, opts: PlacementOpts
    ) -> None:
        """
        Update indicator label and position along the resolved track.

        :param sortletter: Custom label or fallback to ListItem.SortLetter if None.
        :param scroll_id: Scrollbar control ID override for this update.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/…).
        """
        expected = sortletter or infolabel("ListItem.SortLetter")
        fraction = self._fraction_from_scrollbar(to_int(scroll_id, self.scroll_id))

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )

        try:
            btn = self.window.getControl(self.btn_id)
        except RuntimeError:
            log.debug(f"{self.__class__.__name__}: Button {self.btn_id} not found.")
            return

        btn_w = btn.getWidth() or self.btn_width
        btn_h = btn.getHeight() or self.btn_width
        horizontal = width >= height

        if horizontal:
            btn_posx = axis_travel(posx, width, btn_w, fraction)
            btn_posy = (
                btn.getY()
                if opts.relative
                else align_y(posy, height, btn_h, opts.valign, opts.vpad)
            )
        else:
            btn_posy = axis_travel(posy, height, btn_h, fraction)
            btn_posx = (
                btn.getX()
                if opts.relative
                else align_x(posx, width, btn_w, opts.halign, opts.hpad)
            )

        btn.setLabel(expected)
        btn.setPosition(btn_posx, btn_posy)
        log.debug(f"{self.__class__.__name__}: UPDATED → '{expected}'")


class ProgressBarManager:
    """
    Calculates playback or set progress for a focused item and
    positions the corresponding progress bar UI elements.
    """

    def __init__(
        self,
        target: str,
        base_id: int = 4030,
        btn_width: int = 30,
    ) -> None:
        """
        Initialize default control IDs and sizing.

        :param target: InfoLabel prefix (e.g. "ListItem" or "Container(50).ListItem").
        :param base_id: Base group ID that wraps the bar/btn.
        :param btn_width: Fallback thumb size if control reports zero.
        """
        self.window = Window(getCurrentWindowId())
        self.target = target
        self.base_id = int(base_id)
        self.backing_id = base_id + 1
        self.progress_id = base_id + 2
        self.btn_id = base_id + 3
        self.btn_width = btn_width
        self.infolabels = get_infolabels(
            self.target,
            [
                "DBType",
                "PercentPlayed",
                "Property(WatchedEpisodePercent)",
                "Property(WatchedProgress)",
                "Property(UnwatchedEpisodes)",
            ],
        )

    def calculate(self) -> tuple[int, str]:
        """
        Compute percent and unwatched label for the item referenced by ``target``.

        :param set_target: Container id string holding movie set, or None.
        :return: (percent float [0-100], unwatched label as string)
        """

        unwatched = self.infolabels["Property(UnwatchedEpisodes)"]
        for p in [
            self.infolabels["PercentPlayed"],
            self.infolabels["Property(WatchedEpisodePercent)"],
            self.infolabels["Property(WatchedProgress)"],
        ]:
            if p.isdigit() and (resume := int(p)) > 0:
                return resume, unwatched

        if condition(
            f"String.IsEqual({self.target}.Overlay,OverlayWatched.png) | "
            f"Integer.IsGreater({self.target}.PlayCount,0)"
        ):
            return 100, ""

        if "set" in self.infolabels["DBType"]:
            set_id = int(infolabel("ListItem.DBID") or 0)
            if not set_id:
                return 0, ""

            response = json_call(
                method="VideoLibrary.GetMovieSetDetails",
                params={
                    "setid": int(set_id),
                    "movies": {"properties": ["playcount"], "limits": {"start": 0}},
                },
                parent=self.__class__.__name__,
            )
            movies = response.get("result", {}).get("setdetails", {}).get("movies", [])

            total = len(movies)
            if not total:
                return 0, ""

            watched = sum(1 for m in movies if m.get("playcount"))
            return ((total and watched / total or 0) * 100), (
                total - watched
            )  # https://stackoverflow.com/a/68118106/21112145 to avoid ZeroDivisionError

        return 0, unwatched

    def update(
        self,
        percent: float,
        *,
        opts: PlacementOpts,
        base_id: int | None = None,
        backing_id: int | None = None,
        progress_id: int | None = None,
        btn_id: int | None = None,
    ) -> None:
        """
        Resolve rect, move/size controls, and position the thumb.

        :param percent: Unified progress percentage (0-100).
        :param opts: Placement options (coords/anchor/inset/track_w/track_h).
        :param base_id: Optional override for base group ID.
        :param backing_id: Optional override for backing texture ID.
        :param progress_id: Optional override for progress bar ID.
        :param btn_id: Optional override for thumb button ID.
        """
        base_id = to_int(base_id, self.base_id)
        backing_id = to_int(backing_id, self.backing_id)
        progress_id = to_int(progress_id, self.progress_id)
        btn_id = to_int(btn_id, self.btn_id)

        try:
            base = self.window.getControl(base_id)
            progress = self.window.getControl(progress_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__}: base_id {base_id} or progress_id {progress_id} not found."
            )
            return

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )

        if width <= 0 or height <= 0:
            log.debug(
                f"{self.__class__.__name__}: Zero-size rect → ({posx},{posy},{width},{height}); aborting."
            )
            return

        # Position/sizing
        base.setPosition(posx, posy)
        progress.setWidth(width)
        progress.setHeight(height)

        try:
            backing = self.window.getControl(backing_id)
        except RuntimeError:
            backing = None
            log.debug(
                f"{self.__class__.__name__}: Optional backing_id {backing_id} not found."
            )
        else:
            backing.setWidth(width)
            backing.setHeight(height)

        try:
            cur_w, cur_h = base.getWidth(), base.getHeight()
        except Exception:
            cur_w = cur_h = 0
        new_w = max(cur_w or 0, width)
        new_h = max(cur_h or 0, height)
        if new_w != (cur_w or 0) or new_h != (cur_h or 0):
            base.setWidth(new_w)
            base.setHeight(new_h)

        try:
            button = self.window.getControl(btn_id)
        except RuntimeError:
            button = None
            log.debug(f"{self.__class__.__name__}: Optional btn_id {btn_id} not found.")
        else:
            btn_w = button.getWidth() or self.btn_width
            btn_h = button.getHeight() or self.btn_width
            travel = max(0, width - btn_w)
            fraction = max(0.0, min(1.0, (percent or 0) / 100.0))
            btn_posx = int(fraction * travel)
            btn_posy = int((height - btn_h) / 2)
            button.setPosition(btn_posx, btn_posy)


class TextTruncator:
    _ABBREV_EN = {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "mt",
        "ft",
        "rd",
        "ave",
        "blvd",
        "vs",
        "etc",
        "ie",
        "eg",
        "inc",
        "ltd",
        "dept",
        "u",
        "us",
        "uk",
        "eu",
        "u.s",
        "u.k",
    }

    def __init__(
        self,
        measure_ctrl_id: int,
        sleep_ms: int = 6,
        confirm_ms: int = 3,
        safety_chars: int = 3,
        ellipsis: str = "...",
        abbrev_set: set[str] | None = None,
    ) -> None:
        """
        Configure a truncator that probes a hidden measuring TextBox.
        Timing, punctuation safety and abbreviation rules are customizable.

        :param measure_ctrl_id: ID of the TextBox control used to detect overflow.
        :param sleep_ms: Delay (ms) before each overflow check to let layout settle.
        :param confirm_ms: Extra delay (ms) for a second "fits" confirmation.
        :param safety_chars: Conservative backoff (chars) from the probe index.
        :param ellipsis: Ellipsis string to append to truncated output.
        :param abbrev_set: Lowercased abbreviations to suppress sentence caps.
        """
        self.measure_ctrl_id = int(measure_ctrl_id or 0)
        self.window = Window(getCurrentWindowId())
        self.sleep_ms = int(sleep_ms)
        self.confirm_ms = int(confirm_ms)
        self.safety_chars = int(safety_chars)
        self.ellipsis = ellipsis
        self.abbrev = abbrev_set or self._ABBREV_EN
        self._last_len = 0

    def truncate(
        self, text: str, min_safe: int | None = None, smart_cap: bool = False
    ) -> str:
        """
        Return the longest prefix that fits the measuring control.
        Uses coarse refinement around min_safe or bounded binary search.

        :param text: Full input string to measure and truncate.
        :param min_safe: Seed character count known to usually fit (optional).
        :param smart_cap: If True, prefer ending at a full sentence boundary.
        :return: Truncated string (or original if already fits).
        """
        if not text or not self.measure_ctrl_id:
            return ""
        ctrl = self._get_ctrl()
        if ctrl is None:
            return text

        self._probes = 0
        cond_str = f"Container({self.measure_ctrl_id}).HasNext"

        # quick path: whole text fits
        self._set_and_probe(ctrl, text)
        if self._fits(cond_str):
            return text

        base = text.rstrip()
        if base.endswith(self.ellipsis):
            base = base[: -len(self.ellipsis)].rstrip()
        n = len(base)

        if min_safe and min_safe > 0:
            out = self._refine_coarse(ctrl, cond_str, base, min_safe=min_safe, n=n)
        else:
            out = self._search_bounded(ctrl, cond_str, base, n=n)

        mode = "coarse" if (min_safe and min_safe > 0) else "binary"
        delta = self._last_len - (min_safe or 0)
        log.debug(
            f"Trunc: probes={self._probes} "
            f"{mode=} "
            f"{min_safe or 0=} "
            f"final_len={self._last_len} "
            f"{delta=}"
        )

        return self._smart_sentence_cap(out, min_safe) if smart_cap else out

    def _set_and_probe(self, ctrl, text: str) -> None:
        """
        Set TextBox text and count it as a measurement probe.
        Used to track UI roundtrips for diagnostics.

        :param ctrl: Measuring TextBox control instance.
        :param text: Candidate string to set into the control.
        """
        ctrl.setText(text)
        self._probes += 1

    def _get_ctrl(self):
        """
        Fetch and return the measuring TextBox control.
        Handles failures gracefully with a log.

        :return: Control instance or None if not found.
        """
        try:
            return self.window.getControl(self.measure_ctrl_id)
        except Exception:
            log.debug(
                f"{self.__class__.__name__}: measure control {self.measure_ctrl_id} not found"
            )
            return None

    def _fits(self, cond_str: str) -> bool:
        """
        Check if the current TextBox content fits (no overflow).
        Applies a short sleep and a confirm pass to avoid stale reads.

        :param cond_str: Boolean condition string (e.g. "Container(id).HasNext").
        :return: True if fits, False if overflowing.
        """
        # "double-check on fits" to avoid stale false negatives
        xbmc.sleep(self.sleep_ms)
        ok = not condition(cond_str)
        if ok:
            xbmc.sleep(self.confirm_ms)
            ok = not condition(cond_str)
        return ok

    def _slice(self, src: str, upto: int) -> str:
        """
        Produce a safe ellipsized slice near 'upto'.
        Prefers word boundary, trims trailing punctuation, then appends ellipsis.

        :param src: Source text to slice from.
        :param upto: Target cut index before safety backoff is applied.
        :return: Candidate string with ellipsis (or original if short).
        """
        upto = max(0, upto - self.safety_chars)
        if upto >= len(src):
            return src
        cut = src.rfind(" ", 0, max(1, upto))  # prefer word boundary
        if cut == -1:
            cut = upto
        stem = src[:cut].rstrip()
        # tidy trailing punctuation → avoid ", …" or "….", etc.
        stem = stem.rstrip(".,;:!?…-–—")
        stem = stem.rstrip("\"')]}»”’")
        return stem + self.ellipsis

    @log.duration
    def _refine_coarse(
        self, ctrl, cond_str: str, base: str, *, min_safe: int, n: int
    ) -> str:
        """
        Refine around a known-safe seed length using ladder steps.
        Grows then shrinks in coarse steps to converge quickly.

        :param ctrl: Measuring TextBox control instance.
        :param cond_str: Boolean condition string for overflow checks.
        :param base: Preprocessed text (no trailing ellipsis/whitespace).
        :param min_safe: Seed length assumed to be close to the limit.
        :param n: Total length of the base string.
        :return: Best-fitting candidate discovered near the seed.
        """
        guess = max(1, min(min_safe, n))
        steps = (30, 12, 6)

        cand = self._slice(base, guess)
        self._set_and_probe(ctrl, cand)
        if self._fits(cond_str):
            best, cur = cand, guess
            # grow ladder
            for step in steps:
                while True:
                    nxt = min(n, cur + step)
                    if nxt == cur:
                        break
                    cand = self._slice(base, nxt)
                    self._set_and_probe(ctrl, cand)
                    if self._fits(cond_str):
                        best, cur = cand, nxt
                    else:
                        break
            self._last_len = len(best)
            return best

        # shrink ladder
        best, cur = "", guess
        for step in steps:
            while True:
                nxt = max(1, cur - step)
                if nxt == cur:
                    break
                cand = self._slice(base, nxt)
                self._set_and_probe(ctrl, cand)
                if self._fits(cond_str):
                    best, cur = cand, nxt
                    break
                cur = nxt
        return best or self._slice(base, max(1, guess // 2))

    @log.duration
    def _search_bounded(self, ctrl, cond_str: str, base: str, *, n: int) -> str:
        """
        Find the fit point with a bounded binary search.
        Searches [0..n) with conservative iteration caps.

        :param ctrl: Measuring TextBox control instance.
        :param cond_str: Boolean condition string for overflow checks.
        :param base: Preprocessed text (no trailing ellipsis/whitespace).
        :param n: Total length of the base string.
        :return: Best-fitting candidate or a minimal fallback.
        """
        max_iters = min(15, math.ceil(math.log2(max(2, n))) + 1)
        lo, hi, best, iters = 0, n, "", 0
        while lo < hi and iters < max_iters:
            iters += 1
            mid = (lo + hi) // 2
            cand = self._slice(base, mid)
            self._set_and_probe(ctrl, cand)
            if self._fits(cond_str):
                best, lo = cand, mid + 1
            else:
                hi = mid
        if not best:
            best = self._slice(base, 1)
        self._last_len = len(best)
        return best

    def _smart_sentence_cap(self, s: str, min_safe: int | None = None) -> str:
        """
        Prefer cutting at the last full sentence within the candidate.
        Skips common abbreviations and requires next-token capitalization.

        :param s: Candidate result (possibly ending with an ellipsis).
        :param min_safe: Optional seed used to gate very short strings.
        :return: Sentence-capped string (with/without ellipsis as appropriate).
        """
        if len(s) < max(60, (min_safe // 2) if min_safe else 0):
            return s

        # Work on the core without ellipsis; we’ll re-append later.
        core = s[: -len(self.ellipsis)].rstrip() if s.endswith(self.ellipsis) else s

        # Scan for sentence-ending punctuation.
        # We'll examine matches of [.!?]\s+ and post-validate.
        boundaries = []
        i = 0
        while i < len(core):
            ch = core[i]
            if ch in ".!?":
                # look ahead over spaces/quotes to the next visible char
                j = i + 1
                while j < len(core) and core[j] in " \t\n\r\"'»”’)]}":
                    j += 1

                # prev token (before punctuation), normalized
                token = core[:i].rstrip()
                prev = token.rsplit(" ", 1)[-1].strip(" \"')]}»”’").lower().rstrip(".")

                if len(prev) == 1 and prev.isalpha():
                    i += 1
                    continue

                # heuristic: not an abbreviation AND next char is uppercase (if any)
                next_ok = (j >= len(core)) or core[j].isupper()
                if prev not in self.abbrev and next_ok:
                    boundaries.append(i)  # accept this as a sentence boundary
            i += 1

        if not boundaries:
            return s  # no safe earlier boundary

        # take the last acceptable boundary
        end = boundaries[-1] + 1  # include the punctuation
        capped = core[:end].rstrip()

        if capped and capped[-1] not in ".!?":
            # partial phrase — keep ellipsis
            return (capped + " " + self.ellipsis).strip()
        else:
            # full sentence — no ellipsis
            return capped.strip()


class TypewriterAnimation:
    """
    Typewriter text effect with PlacementOpts-driven positioning.
    Height grows per line up to max_lines unless track_h is provided.
    """

    def __init__(
        self,
        control_id: int = 8760,
        step_time: float = 0.025,
        default_line_step: int = 30,
        max_lines: int = 3,
    ):
        """
        :param control_id: Default text control id to animate if none is passed.
        :param step_time: Delay per character (seconds).
        :param default_line_step: Pixels added per wrapped line.
        :param max_lines: Max number of lines grown if track_h not set.
        """
        self.window = Window(getCurrentWindowId())
        self.control_id = int(control_id)
        self.step_time = step_time
        self.default_line_step = default_line_step
        self.max_lines = max_lines

    def update(
        self,
        *,
        label: str,
        opts: PlacementOpts,
        label_id: int | None = None,
        line_step: int | None = None,
        max_lines: int | None = None,
        alive: Callable[[], bool] | None = None,
    ) -> None:
        """
        Animate label with a typewriter effect using compute_rect placement.

        :param label: Text to animate.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/halign/valign/hpad/vpad).
        :param label_id: Optional override control id.
        :param line_step: Pixels added per wrapped line (defaults to default_line_step).
        :param max_lines: Optional cap for number of lines (overrides default).
        :param expected_identity: Focus snapshot for guarding.
        :param alive: Optional guard callable; return False to abort animation.
        """

        def _alive() -> bool:
            if alive is not None:
                ok = alive()
                if not ok:
                    log.debug(
                        f"{self.__class__.__name__}: ABORTED → '{label}' lost focus"
                    )
                return ok
            return True

        log.debug(f"{self.__class__.__name__} → START → '{label}'")
        control_id = to_int(label_id, self.control_id)

        if not _alive():
            return

        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log.debug(f"{self.__class__.__name__}: Control {control_id} not found")
            return

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
            content_h=(
                (self.default_line_step * self.max_lines) if not opts.track_h else None
            ),
        )

        step_h = max(1, int(line_step or self.default_line_step))
        base_h = max(1, int(opts.track_h or step_h))

        # Bottom-align a one-line box inside the rect (or top/center as requested).
        posy_aligned = align_y(posy, height, base_h, align=opts.valign, pad=opts.vpad)
        posx_final, posy_final, width_final, height_final = (
            posx,
            posy_aligned,
            width,
            base_h,
        )

        control.setWidth(width_final)
        control.setHeight(height_final)
        control.setPosition(posx_final, posy_final)

        if not _alive():
            control.setText("")
            return

        # Animate: add step_h per wrap, up to max_lines
        max_lines_eff = max_lines or self.max_lines
        max_height = base_h + (max_lines_eff - 1) * step_h
        current_height = base_h
        current_posy = posy_final

        control.setVisible(True)
        for i in range(1, len(label) + 1):
            if not _alive():
                control.setText("")
                return

            sub = label[:i]
            control.setText(sub)
            xbmc.sleep(int(self.step_time * 1000))
            if (
                i > 1
                and condition(f"Container({control_id}).HasNext")
                and current_height < max_height
            ):
                next_h = min(current_height + step_h, max_height)
                dy = next_h - current_height
                current_height = next_h

                # Only shift Y to keep the bottom fixed when valign=bottom.
                if (opts.valign or "center").lower() == "bottom":
                    current_posy -= dy

                control.setHeight(current_height)
                control.setPosition(posx_final, current_posy)

                # Reflow nudge: temporarily append a zero-width space, then revert
                control.setText(sub + "\u200b")
                xbmc.sleep(1)
                control.setText(sub)

        log.debug(f"{self.__class__.__name__} → DONE → '{label}'")
