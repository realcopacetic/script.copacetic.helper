# author: realcopacetic

from typing import Callable, Iterable
import math
import re

from xbmcgui import Window, getCurrentWindowId

from resources.lib.plugin.geometry import (
    PlacementOpts,
    align_x,
    align_y,
    axis_travel,
    compute_rect,
)
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    log,
    return_label,
    split,
    split_random,
    to_int,
    url_encode,
    window_property,
    xbmc,
)


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
        truncate_label: str | None = None,
        truncate_id: int | None = None,
    ) -> None:
        """
        Initialize the handler with listitem, dbtype and dbid.

        :param target: InfoLabel prefix (e.g. "ListItem" or "Container(50).ListItem").
        :param dbtype: Database content type (e.g. video or tvshow).
        :param dbid: Database ID for the given item.
        """
        self.target = target
        self.dbtype = dbtype
        self.dbid = dbid
        self.truncate_label = truncate_label
        self.truncate_id = truncate_id or 0
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
        self.fetched = self.fetch_data()

    def fetch_data(self) -> dict[str, object]:
        """
        Build a normalized metadata dictionary.

        :return: Dictionary with art, resume, contributors, etc.
        """
        label = return_label(self.infolabels["Label"])
        encoded_label = url_encode(label)
        return {
            "file": encoded_label,
            "label": encoded_label,
            "label2": label,
            "director": split_random(self.infolabels["Director"]),
            "dbtype": self.dbtype,
            "genre": split_random(self.infolabels["Genre"]),
            "studio": self._studio(),
            "truncated_label": self._binary_truncate_on_control(
                        measure_ctrl_id=self.truncate_id,
                        text=self.truncate_label,
                        ellipsis="...",
                    ), 
            "writer": split(self.infolabels["Writer"]),
        }

    @staticmethod
    def _binary_truncate_on_control(
        measure_ctrl_id: int,
        text: str,
        sleep_ms: int = 8,
        confirm_ms: int = 4,
        max_iters: int | None = None,
        ellipsis: str = "...",
        safety_chars: int = 3,
    ) -> str:
        if not text or not measure_ctrl_id:
            return ""

        win = Window(getCurrentWindowId())
        try:
            ctrl = win.getControl(int(measure_ctrl_id))
        except Exception:
            log(f"binary_truncate: measure control {measure_ctrl_id} not found")
            return text

        prop_key = f"trunc.last.{measure_ctrl_id}"  # seed cache
        cond_str = f"Container({measure_ctrl_id}).HasNext"

        def fits() -> bool:
            """Return True if it fits (no overflow), with one quick confirm on 'fits'."""
            xbmc.sleep(sleep_ms)
            ok = not condition(cond_str)
            if ok:
                xbmc.sleep(confirm_ms)  # quick confirm on 'fits'
                ok = not condition(cond_str)
            return ok

        def slice_with_ellipsis(src: str, upto: int) -> str:
            upto = max(0, upto - safety_chars)
            if upto >= len(src):
                return src

            cut = src.rfind(" ", 0, max(1, upto))  # prefer word boundary
            if cut == -1:
                cut = upto

            stem = src[:cut].rstrip()
            stem = stem.rstrip(".,;:!?…-–—")  # trim terminal punctuation
            stem = stem.rstrip("\"')]}»”’")  # trim dangling closers
            return stem + ellipsis

        ctrl.setText(text)  # quick path: whole text fits
        if fits():
            win.setProperty(prop_key, str(len(text)))
            return text

        base = text.rstrip()
        if base.endswith(ellipsis):
            base = base[: -len(ellipsis)].rstrip()

        if max_iters is None:  # adaptive iteration bound
            max_iters = min(16, math.ceil(math.log2(max(2, len(base)))) + 2)

        # Seed lo/hi around last accepted length (if any)
        try:
            guess = int(win.getProperty(prop_key) or 0)
        except ValueError:
            guess = 0

        lo = 0
        hi = len(base)

        if guess > 0:
            # Start near last success; widen if needed during search
            lo = max(0, guess - 64)
            hi = min(len(base), guess + 256)

        best = ""
        iters = 0
        while lo < hi and iters < max_iters:
            iters += 1
            mid = (lo + hi) // 2
            cand = slice_with_ellipsis(base, mid)
            ctrl.setText(cand)
            if fits():  # trust only confirmed 'fits'
                best = cand
                lo = mid + 1
            else:
                hi = mid

        if not best:
            best = slice_with_ellipsis(base, 1)

        # remember the rough character count (sans ellipsis) for next items
        sans = best[: -len(ellipsis)] if best.endswith(ellipsis) else best
        win.setProperty(prop_key, str(len(sans)))

        return best

    def _studio(self) -> str:
        """
        Returns first studio name, cleaned of '+'.

        :return: Studio string or empty string.
        """
        studio = (
            split(infolabel("Container(3100).ListItem(-1).Studio"))
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
        :return: None
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
            log(f"{self.__class__.__name__}: Button {self.btn_id} not found.")
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
        log(f"{self.__class__.__name__}: UPDATED → '{expected}'")


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

    def calculate(self, set_target: str | None = None) -> tuple[int, str]:
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

        if set_target and "set" in self.infolabels["DBType"]:
            total = int(infolabel(f"Container({set_target}).NumItems") or 0)
            watched = sum(
                condition(
                    f"Integer.IsGreater(Container({set_target}).ListItem({x}).PlayCount,0)"
                )
                for x in range(total)
            )
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
            log(
                f"{self.__class__.__name__}: base_id {base_id} or progress_id {progress_id} not found."
            )
            return

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )

        if width <= 0 or height <= 0:
            log(
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
            log(
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
            log(f"{self.__class__.__name__}: Optional btn_id {btn_id} not found.")
        else:
            btn_w = button.getWidth() or self.btn_width
            btn_h = button.getHeight() or self.btn_width
            travel = max(0, width - btn_w)
            fraction = max(0.0, min(1.0, (percent or 0) / 100.0))
            btn_posx = int(fraction * travel)
            btn_posy = int((height - btn_h) / 2)
            button.setPosition(btn_posx, btn_posy)


class TextTruncator:
    """
    Measure-on-control truncator.

    - Uses Container(<measure_ctrl_id>).HasNext to detect overflow on a hidden TextBox.
    - If min_safe is given → fast coarse-step refine around that seed.
    - Else → bounded binary search with adaptive cap.
    - Optional smart_cap trims to the last full sentence (with abbrev guards).
    """

    _ABBREV = {
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
        # Regions/initialisms
        "u",
        "us",
        "uk",
        "eu",
        "u.s",
        "u.k",
    }

    # single pass regex to find sentence boundaries while guarding abbreviations:
    # split on ". " or "? " or "! " only when the token before the period
    # isn't in abbreviation list. Post-filter too.
    _BOUNDARY_RE = re.compile(r"([.?!])\s+")

    def __init__(
        self,
        measure_ctrl_id: int,
        sleep_ms: int = 8,
        confirm_ms: int = 4,
        safety_chars: int = 3,
        ellipsis: str = "...",
    ) -> None:
        self.measure_ctrl_id = int(measure_ctrl_id or 0)
        self.window = Window(getCurrentWindowId())
        self.sleep_ms = int(sleep_ms)
        self.confirm_ms = int(confirm_ms)
        self.safety_chars = int(safety_chars)
        self.ellipsis = ellipsis

    def truncate(
        self,
        text: str,
        min_safe: int | None = None,
        smart_cap: bool = False,
    ) -> str:
        """
        Return a truncated version of `text` that fits in measure_ctrl_id.
        Never returns None; returns "" if input/ctrl invalid.

        :param text: Text to fit.
        :param min_safe: Optional seed (e.g. 192) for coarse refine.
        :param smart_cap: If True, cap final result to last full sentence.
        """
        if not text or not self.measure_ctrl_id:
            return ""

        ctrl = self._get_ctrl()
        if ctrl is None:
            return text

        cond_str = f"Container({self.measure_ctrl_id}).HasNext"

        # Quick path: full text fits
        ctrl.setText(text)
        if self._fits(cond_str):
            out = text
            return self._smart_sentence_cap(out) if smart_cap else out

        base = text.rstrip()
        if base.endswith(self.ellipsis):
            base = base[: -len(self.ellipsis)].rstrip()
        n = len(base)

        if min_safe and min_safe > 0:
            out = self._refine_coarse(ctrl, cond_str, base, min_safe=min_safe, n=n)
        else:
            out = self._search_bounded(ctrl, cond_str, base, n=n)

        return self._smart_sentence_cap(out) if smart_cap else out

    def _get_ctrl(self):
        try:
            return self.window.getControl(self.measure_ctrl_id)
        except Exception:
            log(
                f"{self.__class__.__name__}: measure control {self.measure_ctrl_id} not found"
            )
            return None

    def _fits(self, cond_str: str) -> bool:
        # "double-check on fits" to avoid stale false negatives
        xbmc.sleep(self.sleep_ms)
        ok = not condition(cond_str)
        if ok:
            xbmc.sleep(self.confirm_ms)
            ok = not condition(cond_str)
        return ok

    def _slice(self, src: str, upto: int) -> str:
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

    def _refine_coarse(
        self, ctrl, cond_str: str, base: str, *, min_safe: int, n: int
    ) -> str:
        guess = max(1, min(min_safe, n))
        steps = (24, 12, 6)

        cand = self._slice(base, guess)
        ctrl.setText(cand)
        if self._fits(cond_str):
            best, cur = cand, guess
            # grow ladder
            for step in steps:
                while True:
                    nxt = min(n, cur + step)
                    if nxt == cur:
                        break
                    cand = self._slice(base, nxt)
                    ctrl.setText(cand)
                    if self._fits(cond_str):
                        best, cur = cand, nxt
                    else:
                        break
            return best

        # shrink ladder
        best, cur = "", guess
        for step in steps:
            while True:
                nxt = max(1, cur - step)
                if nxt == cur:
                    break
                cand = self._slice(base, nxt)
                ctrl.setText(cand)
                if self._fits(cond_str):
                    best, cur = cand, nxt
                    break
                cur = nxt
        return best or self._slice(base, max(1, guess // 2))

    def _search_bounded(self, ctrl, cond_str: str, base: str, *, n: int) -> str:
        max_iters = min(16, math.ceil(math.log2(max(2, n))) + 2)
        lo, hi, best, iters = 0, n, "", 0
        while lo < hi and iters < max_iters:
            iters += 1
            mid = (lo + hi) // 2
            cand = self._slice(base, mid)
            ctrl.setText(cand)
            if self._fits(cond_str):
                best, lo = cand, mid + 1
            else:
                hi = mid
        return best or self._slice(base, 1)

    def _smart_sentence_cap(self, s: str) -> str:
        """
        Prefer ending at the last complete sentence within s.
        Heuristic, ~99%: avoid treating known abbreviations as sentence boundaries.
        If no earlier clean boundary is found, return s unchanged.
        """
        # If there's no ellipsis or string is short, leave it alone
        if len(s) < 80:
            return s

        # We only try to cap when we already truncated (ends with ellipsis)
        truncated = s.endswith(self.ellipsis)
        core = s[: -len(self.ellipsis)].rstrip() if truncated else s

        parts = []
        start = 0
        for m in self._BOUNDARY_RE.finditer(core):
            end = m.end(1)  # position of the punctuation mark
            token = core[:end].rstrip()
            # word before the punctuation
            prev = token.rsplit(" ", 1)[-1].strip(" \"')]}»”’").lower().rstrip(".")
            if prev in self._ABBREV:
                continue  # skip abbreviation as boundary
            parts.append(core[start:end])  # include the punctuation
            start = m.end()  # after the space

        if not parts:
            return s  # no safe earlier boundary detected

        capped = " ".join(p.strip() for p in parts).rstrip()
        # Ensure final punctuation
        if capped and capped[-1] not in ".!?":
            capped = capped.rstrip(". ") + "."

        return capped if not truncated else (capped + " " + self.ellipsis).strip()


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
        :param line_height: Pixels added per wrapped line.
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
        expected_identity: str | None = None,
        identity_getter: Callable[[], str] | None = None,
    ) -> None:
        """
        Animate label with a typewriter effect using compute_rect placement.

        :param label: Text to animate.
        :param opts: Placement options (coords/anchor_id/inset/track_w/track_h/halign/valign/hpad/vpad).
        :param label_id: Optional override control id.
        :param line_step: Pixels added per wrapped line (defaults to default_line_step).
        :param max_lines: Optional cap for number of lines (overrides default).
        :param expected_identity: Focus snapshot for guarding.
        :param identity_getter: Returns current identity for guard checks.
        :return: None
        """

        def alive() -> bool:
            if identity_getter and expected_identity is not None:
                if not (ok := identity_getter() == expected_identity):
                    log(f"{self.__class__.__name__}: ABORTED → '{label}' lost focus")
                return ok
            return True

        log(f"{self.__class__.__name__}: START → '{label}'")
        control_id = to_int(label_id, self.control_id)

        if not alive():
            return

        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            log(f"{self.__class__.__name__}: Control {control_id} not found")
            return

        posx, posy, width, height = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
            content_h=(self.line_height * self.max_lines) if not opts.track_h else None,
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

        if not alive():
            control.setText("")
            return

        # Animate: add step_h per wrap, up to max_lines
        max_lines_eff = max_lines or self.max_lines
        max_height = base_h + (max_lines_eff - 1) * step_h
        current_height = base_h
        current_posy = posy_final

        control.setVisible(True)
        for i in range(1, len(label) + 1):
            if not alive():
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

        log(f"{self.__class__.__name__}: DONE → '{label}'")
