"""
Run the artwork pipeline (prepare, then compose) on synthetic posters outside Kodi.

Checks the label's measured rect (lines, widest line), the element-on-art step, its
winning colour, the band's PNG and alpha (solid over the label's lines, 0 a feather
away) and, at step 3, that the tinted band reads at the ratio, then that a palette
PNG's transparent colour is no colour, that a row measured before the measure version
is measured again, that an RGB PNG with tRNS measures as its RGBA copy, that an
image Kodi recached in the other format measures its newer copy and that a photo-sized
JPEG decodes scaled down for a blur but whole for its size, and that a local source
opens in place where a share's is copied; prints
each serve's time. Needs Pillow and the skin (its Font.xml and fonts measure the
label); no network.

    python tests/artwork_check.py ../skin.copacetic2
"""

import io
import json
import os
import random
import shutil
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Callable

from build_offline import HELPER, install_stubs
from PIL import Image, ImageChops, ImageDraw

GHOSTED, GUNMETAL = "fff0efef", "ff312124"
STRIP = {
    "icon_blur": "true",
    "icon_blur_radius": "4",
    "icon_darken": "true",
    "icon_darken_rects": "20,577,440,123",  # the typewriter's text box, 3 lines
    "icon_darken_frame": "480,720",
    "icon_darken_label": "Mission Impossible Dead",
    "icon_darken_label_font": "description_l",
    "icon_darken_label_pitch": "-41",
    "icon_element_colors": f"{GHOSTED},{GUNMETAL}",
}


SHAPES = (  # file, size, mode, one corner cut out, (width, height, opaque)
    ("full.png", (512, 512), "RGBA", False, (512, 512, 1)),
    ("rounded.png", (512, 512), "RGBA", True, (512, 512, 0)),
    ("plain.jpg", (640, 512), "RGB", False, (640, 512, 1)),
    ("press.jpg", (256, 256), "CMYK", False, (256, 256, 1)),
)


def noise(img: Image.Image, _: ImageDraw.ImageDraw) -> None:
    """Fill the poster with random colour noise: busy, mid-grey once blurred."""
    rng = random.Random(1)
    img.putdata([tuple(rng.randrange(256) for _ in "rgb") for _ in range(480 * 720)])


LABELS = {  # label: its rect in the strip poster's text box, one to three lines
    "Up •\xa02009": (20, 659, 146, 41),
    "Radiohead • OK Computer •\xa01997": (20, 618, 372, 82),  # "• 1997" holds
    "Mission: Impossible – Dead Reckoning Part One •\xa02023": (20, 618, 384, 82),
    "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb "
    "•\xa01964": (20, 577, 437, 123),
    "Borat: Cultural Learnings of America for Make Benefit Glorious Nation of "
    "Kazakhstan •\xa02006": (
        20,
        577,
        429,
        123,
    ),  # four lines, capped at the box's three
    "Supercalifragilisticexpialidociousness •\xa02000": (20, 618, 434, 82),  # cut
}

POSTERS = {  # name: (draw, step, winner, darken)
    "white": (lambda _, d: d.rectangle((0, 0, 480, 720), "white"), 1, GUNMETAL, 47),
    "dark": (lambda _, d: d.rectangle((0, 0, 480, 720), "#141418"), 1, GHOSTED, 0),
    "busy noise": (noise, 2, GUNMETAL, None),
    "straddle": (
        lambda _, d: (
            d.rectangle((0, 0, 240, 720), fill="#08080a"),
            d.rectangle((240, 0, 480, 720), fill="#f5f5f5"),
        ),
        3,
        GHOSTED,
        None,
    ),
    "bright patch": (
        lambda _, d: (
            d.rectangle((0, 0, 480, 720), fill="#231d27"),
            d.rectangle((60, 650, 200, 720), fill="#f0e6d2"),
        ),
        3,
        GHOSTED,
        None,
    ),
    "dark patch": (  # the lift: dark red on white, as Fallout's trousers
        lambda _, d: (
            d.rectangle((0, 0, 480, 720), fill="white"),
            d.rectangle((60, 650, 200, 720), fill="#5a0a10"),
        ),
        3,
        GUNMETAL,
        None,
    ),
    "blue patch": (  # the lift where blue clips at white and barely lifts a grey
        lambda _, d: (
            d.rectangle((0, 0, 480, 720), fill="white"),
            d.rectangle((60, 650, 200, 720), fill="#0000fa"),
        ),
        3,
        GUNMETAL,
        None,
    ),
}


def install(tmp: Path, skin: Path) -> None:
    """
    build_offline's stubs, plus the file calls the artwork cache makes.

    :param tmp: Scratch root: add-on data, texture cache and posters.
    :param skin: Skin root, read as special://skin/ for its fonts.
    """
    (tmp / "out" / "temp").mkdir(parents=True)
    install_stubs(HELPER, skin, tmp / "out", verbose=False)
    xbmc, vfs = sys.modules["xbmc"], sys.modules["xbmcvfs"]
    special = vfs.translatePath
    xbmc.getCacheThumbName = lambda url: f"{zlib.crc32(url.encode()):08x}.tbn"
    vfs.translatePath = lambda p: special(p) if p.startswith("special://") else p
    vfs.exists = os.path.exists
    vfs.mkdirs = lambda p: os.makedirs(p, exist_ok=True) or True
    vfs.copy = lambda src, dst: bool(shutil.copy(src, dst))
    vfs.delete = lambda p: os.path.exists(p) and not os.remove(p)

    class File(io.FileIO):
        """xbmcvfs.File: special:// paths, readBytes and the "wb" mode."""

        def __init__(self, path: str, mode: str = "r") -> None:
            super().__init__(vfs.translatePath(path), mode.replace("b", ""))

        readBytes = io.FileIO.readall

    vfs.File = File
    sys.path.insert(0, str(HELPER))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="artwork-check-"))
    install(tmp, Path(sys.argv[1]).resolve())
    from resources.lib.art.analyzer import ColorAnalyzer
    from resources.lib.art.color import contrast, from_hex, luminance
    from resources.lib.art.darken import ColorDarken, ramp
    from resources.lib.art.editor import ImageEditor
    from resources.lib.art.policy import ART_PROCESS_MAP, ColorConfig
    from resources.lib.plugin.opts import ArtOpts

    def serve(params: dict[str, str]) -> tuple[dict, float]:
        art_opts = {t: ArtOpts.from_params(params, t) for t in ART_PROCESS_MAP}
        jobs = {
            t: [p for p in procs if art_opts[t].enabled(p)]
            for t, procs in ART_PROCESS_MAP.items()
            if art_opts[t].url
        }
        t0 = time.perf_counter()
        art = ImageEditor().image_processor(jobs=jobs, art_opts=art_opts)
        return art, (time.perf_counter() - t0) * 1000

    cfg = ColorConfig()
    engine = ColorDarken(ColorAnalyzer(cfg))
    label = engine._clamp_rects_to_labels(ArtOpts.from_params(STRIP, "icon").darken)
    failures = 0
    for text, want in LABELS.items():
        opts = ArtOpts.from_params({**STRIP, "icon_darken_label": text}, "icon")
        got = engine._clamp_rects_to_labels(opts.darken)
        failures += got != [want]
        print(f"{'ok  ' if got == [want] else 'FAIL'} label {got[0]}  {text[:44]!r}")
    for name, (draw, step, winner, darken) in POSTERS.items():
        img = Image.new("RGB", (480, 720))
        draw(img, ImageDraw.Draw(img))
        img.save(path := str(tmp / f"{name}.jpg"), quality=95)
        art, cold = serve({"icon_url": path, **STRIP})
        again, warm = serve({"icon_url": path, **STRIP})
        got, note, ok = 1, "", art == again
        if band := art.get("icon_band"):  # a PNG with alpha; step 3 changed the blur
            image = Image.open(band)
            ok &= (image.format, image.mode) == ("PNG", "RGBA")
            ok &= solid(image, label[0]) and clear(image, label[0], cfg.band_feather)
            shown = Image.new("RGB", image.size)
            seen = image.getchannel("A").point(lambda a: 255 * (a > 0))
            shown.paste(Image.open(art["icon"]), mask=seen)  # the blur, under alpha
            got = (
                3 if ImageChops.difference(shown, image.convert("RGB")).getbbox() else 2
            )
        ok &= (got, art["icon_element_color"]) == (step, winner)
        if darken is not None:
            ok &= art["icon_darken"] == darken
        if got == 3:
            copy = Image.open(band).convert("RGB")
            box = engine.boxes(copy.size, label, STRIP["icon_darken_frame"])[0]
            text = luminance(from_hex(art["icon_element_color"]))
            worst = min(contrast(text, end) for end in engine._extremes(copy, box))
            ok &= worst >= cfg.ratio
            note = f"band reads {worst:.2f}"
        failures += not ok
        print(
            f"{'ok  ' if ok else 'FAIL'} {name:13} step {got} "
            f"{art['icon_element_color']} darken {art['icon_darken']:>3} "
            f"{cold:5.0f} ms uncached, {warm:3.0f} ms cached  {note}"
        )
    narrow = {"icon_url": path, **STRIP, "icon_band_feather": "60"}  # last poster
    image = Image.open(serve(narrow)[0]["icon_band"])
    ok = solid(image, label[0]) and clear(image, label[0], 60)
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} feather 60: clear 60 px past the label's lines")
    straddle = {"icon_url": str(tmp / "straddle.jpg"), **STRIP}  # pulled to its end
    one, two = (  # copied at once: a new band replaces the old file
        Image.open(serve({**straddle, **extra})[0]["icon_band"]).copy()
        for extra in ({}, {"icon_band_inset": "60"})
    )
    alpha, rgb = (  # getbbox on RGBA reads the alpha only
        ImageChops.difference(*(get(i) for i in (one, two))).getbbox()
        for get in (lambda i: i.getchannel("A"), lambda i: i.convert("RGB"))
    )
    ok = alpha is None and rgb is not None
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} inset 60: a new band, same alpha, change moved")
    mask = ramp((200, 100), (40, 40, 60, 60), 40, 60)  # an inset wider than the label
    row = [mask.getpixel((x, 50)) for x in range(38, 43)]
    ok = max(abs(a - b) for a, b in zip(row, row[1:])) <= 3
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} inset wider than the label: no step {row}")
    for name, size, mode, cut, want in SHAPES:
        img = Image.new(mode, size, "white")
        if cut:
            img.putpixel((size[0] - 1, size[1] - 1), (255, 255, 255, 0))
        img.save(path := str(tmp / name))
        params = {"icon_url": path, "icon_shape": "true"}
        art = serve(params)[0]
        got = art["icon_width"], art["icon_height"], art["icon_opaque"]
        ok = got == want and serve(params)[0] == art  # the second serve is the cache's
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} shape {name:12} {got}")
    keyed = Image.new("P", (800, 310))  # palette PNG: index 0, green, is transparent
    keyed.putpalette([0, 255, 0, 200, 16, 46])
    ImageDraw.Draw(keyed).rectangle((60, 80, 740, 230), 1)
    keyed.save(path := str(tmp / "keyed.png"), transparency=0)
    serve({"clearlogo_url": path})
    sqlite = ImageEditor().sqlite
    (row,) = sqlite.find_variants(path, "darken")
    got = json.loads(row["measure"])["dominant"]
    ok = got == "ffc8102e"
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} palette PNG: transparency is not colour {got}")
    key = row["cache_key"]  # as a row measured before the version: no token, green
    old = key.rpartition("&version=")[0]
    sqlite.delete_entry(key)
    sqlite.add_entry({**row, "cache_key": old, "measure": '{"dominant":"ff00ff00"}'})
    serve({"clearlogo_url": path})
    (new,) = sqlite.find_variants(path, "darken")
    ok = bool(old) and new["cache_key"] == key and new["measure"] == row["measure"]
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} measure version: an older row is measured again")
    keyed = Image.new("RGB", (800, 310), "white")  # white is transparent: thin strokes
    draw = ImageDraw.Draw(keyed)
    for x in range(40, 760, 24):
        draw.rectangle((x, 60, x + 4, 250), "#0028a0")
    for y in range(60, 250, 30):
        draw.rectangle((40, y, 760, y + 2), "#0028a0")
    keyed.save(path := str(tmp / "keyed-rgb.png"), transparency=(255, 255, 255))
    Image.open(path).convert("RGBA").save(rgba := str(tmp / "keyed-rgba.png"))
    for p in (path, rgba):
        serve({"clearlogo_url": p})
    got = [sqlite.find_variants(p, "darken")[0]["measure"] for p in (path, rgba)]
    ok = got[0] == got[1]
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} RGB PNG with tRNS measures as its RGBA {got[0]}")
    failures += check_rekey(tmp, serve, ImageEditor())
    failures += check_recache(tmp, serve, ImageEditor())
    failures += check_draft(tmp, serve, ImageEditor)
    failures += check_in_place(tmp, ImageEditor())
    shutil.rmtree(tmp)
    sys.exit(bool(failures))


def check_in_place(tmp: Path, editor: Any) -> bool:
    """
    A source outside Kodi's texture cache opens in place when it is a local file on
    disk; a share's, the web's or a missing file's goes to the temp copy, as before.

    :param tmp: Scratch root, holding the posters.
    :param editor: ImageEditor, for its cache manager.
    :return: True when a check failed.
    """
    vfs, manager, copied = sys.modules["xbmcvfs"], editor.cache_manager, []
    copy, vfs.copy = vfs.copy, lambda src, dst: copied.append(src)
    local, share = str(tmp / "white.jpg"), "smb://nas/pictures/white.jpg"
    gone = str(tmp / "deleted.jpg")  # not on disk: falls through to the copy, as before
    ok = manager.source_path(manager.prepare(local)) == local and not copied
    for path in (share, gone):
        ok &= manager.source_path(manager.prepare(path)) is None and path in copied
    vfs.copy = copy
    print(f"{'ok  ' if ok else 'FAIL'} source: a local file in place, a share copied")
    return not ok


def check_draft(tmp: Path, serve: Callable, editor: type) -> bool:
    """
    A photo-sized JPEG decodes scaled down for a blur and its measure (stored on its
    side too) with the same darken, and whole for a job that reads its size.

    :param tmp: Scratch root for the sources.
    :param serve: Runs a serve from its params; returns (art, ms).
    :param editor: ImageEditor, whose opens are watched.
    :return: True when a check failed.
    """
    photo = Image.new("RGB", (4000, 3000), "#806040")
    ImageDraw.Draw(photo).rectangle((0, 0, 4000, 1000), "#f4f6fa")
    turned = Image.Exif()
    turned[0x0112] = 6  # stored on its side
    blur = {"blur": "true", "edge_trim": "2", "darken": "true"}
    cases = {  # name: (art types, shape, EXIF, the size opened)
        "blur": (("background",), False, None, (1000, 750)),
        "blur, on its side": (("background",), False, turned, (750, 1000)),
        "shape": (("icon",), True, None, (4000, 3000)),
        "blur and shape": (("background", "icon"), True, None, (4000, 3000)),
    }
    opened, opener, drafts, failed = [], editor._image_open, editor._drafts, False

    def watch(self, url: str, draft: int = 0) -> Image.Image | None:
        opened.append(image := opener(self, url, draft))
        return image

    editor._image_open = watch
    for name, (art_types, shape, exif, want) in cases.items():
        params = {f"{t}_{k}": v for t in art_types for k, v in blur.items()}
        params |= {"icon_shape": "true"} if shape else {}
        arts = []
        for copy in ("", " whole"):  # the second decoded whole, to compare
            path = str(tmp / f"draft {name}{copy}.jpg")
            photo.save(path, quality=90, exif=exif or Image.Exif())
            arts.append(serve(params | {f"{t}_url": path for t in art_types}))
            editor._drafts = lambda self, jobs, art_opts: {}
        editor._drafts = drafts
        (art, ms), (whole, whole_ms), first = *arts, art_types[0]
        ok = [image.size for image in opened[:-1]] == [want]  # one open per serve
        ok &= art[f"{first}_darken"] == whole[f"{first}_darken"]
        ok &= Image.open(art[first]).size == Image.open(whole[first]).size
        ok &= not shape or (art["icon_width"], art["icon_height"]) == (4000, 3000)
        failed |= not ok
        print(
            f"{'ok  ' if ok else 'FAIL'} draft {name:17} opened {opened[0].size} "
            f"{ms:4.0f} ms, whole {whole_ms:4.0f} ms"
        )
        opened.clear()
    bad = {"background_url": path, "background_darken_frame": "wide", **params}
    ok = serve(bad)[0] == {}  # logged, not raised out of the serve
    failed |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} draft: a bad frame param serves no art")
    editor._image_open = opener
    return failed


def check_rekey(tmp: Path, serve: Callable, editor: Any) -> bool:
    """
    An opaque .png Kodi caches as .jpg: rows keyed by URL rekey once to the copy's
    hash, old rows and files go, and an updated copy re-measures.

    :param tmp: Scratch root for the source.
    :param serve: Runs a serve from its params; returns (art, ms).
    :param editor: ImageEditor, for the cache's rows and the copy's path.
    :return: True when a check failed.
    """
    img = Image.new("RGB", (480, 720))
    noise(img, None)
    img.save(path := str(tmp / "opaque.png"))
    params = {"icon_url": path, "icon_shape": "true", **STRIP}
    manager = editor.cache_manager
    copy = manager.prepare(path).cached_image_path.with_suffix(".jpg")

    def rows_keyed_by(prefix: str, processes: tuple[str, ...]) -> bool:
        """
        One row per process, its key starting with prefix.

        :param prefix: Start every row's cache key must have.
        :param processes: Art processes to look up.
        :return: True when each process has exactly one such row.
        """
        rows = [editor.sqlite.find_variants(path, p) for p in processes]
        return all(
            len(found) == 1 and found[0]["cache_key"].startswith(prefix)
            for found in rows
        )

    processes = "blur", "darken", "shape", "band"
    old = serve(params)[0]
    ok = rows_keyed_by(path, processes)

    copy.parent.mkdir(parents=True, exist_ok=True)
    img.save(copy, quality=95)
    ctx = manager.prepare(path)
    ok &= ctx.cached_image_path == copy and ctx.cached_thumb == copy.name
    new = serve(params)[0]
    ok &= rows_keyed_by(ctx.cached_file_hash, processes)
    for art in ("icon", "icon_band"):
        ok &= new[art] != old[art] and not os.path.exists(old[art])
        ok &= os.path.exists(new[art])

    img.resize((240, 360)).save(copy, quality=95)
    updated = serve(params)[0]
    ctx = manager.prepare(path)
    ok &= (updated["icon_width"], updated["icon_opaque"]) == (240, 1)
    ok &= rows_keyed_by(ctx.cached_file_hash, processes[:3])
    print(f"{'ok  ' if ok else 'FAIL'} rekey: URL rows to the .jpg copy's hash, once")
    return not ok


def check_recache(tmp: Path, serve: Callable, editor: Any) -> bool:
    """
    A replaced icon Kodi recaches in the other format: Kodi leaves the old copy, so
    the newer copy is measured, both ways (Copacetic 2's RGBA icon went RGB).

    :param tmp: Scratch root for the source.
    :param serve: Runs a serve from its params; returns (art, ms).
    :param editor: ImageEditor, for the copy's path.
    :return: True when a check failed.
    """
    rounded = Image.new("RGBA", (720, 720), "white")  # alpha: Kodi's copy is a .png
    rounded.putpixel((719, 719), (255, 255, 255, 252))
    square = Image.new("RGB", (720, 720), "white")  # no alpha: a .jpg
    ok = True
    for name, old, new, want in (
        ("went-rgb.png", (rounded, ".png"), (square, ".jpg"), 1),
        ("went-rgba.png", (square, ".jpg"), (rounded, ".png"), 0),
    ):
        path = str(tmp / "addon" / name)
        params = {"icon_url": path, "icon_shape": "true"}
        copy = editor.cache_manager.prepare(path).cached_image_path
        copy.parent.mkdir(parents=True, exist_ok=True)
        old[0].save(stale := copy.with_suffix(old[1]))
        os.utime(stale, (time.time() - 86400,) * 2)
        ok &= serve(params)[0]["icon_opaque"] == 1 - want
        new[0].save(copy.with_suffix(new[1]))
        art = serve(params)[0]
        ok &= (art["icon_width"], art["icon_opaque"]) == (720, want)
    print(f"{'ok  ' if ok else 'FAIL'} recache: the newer of Kodi's two copies")
    return not ok


def solid(band: Image.Image, rect: tuple[int, int, int, int]) -> bool:
    """
    The band's alpha is full over the label's measured rect (frame px are blur px).

    :param band: The band, RGBA.
    :param rect: The label's measured rect.
    :return: True when every pixel there is opaque.
    """
    x, y, w, h = rect
    return band.getchannel("A").crop((x, y, x + w, y + h)).getextrema() == (255, 255)


def clear(band: Image.Image, rect: tuple[int, int, int, int], feather: int) -> bool:
    """
    The band's alpha is 0 a feather above the label's lines and a feather past its
    end, and so beyond: the band is the label's width, not the text box's.

    :param band: The band, RGBA.
    :param rect: The label's measured rect.
    :param feather: The band's feather, frame px.
    :return: True when the rows from there up and the columns from there on are clear.
    """
    x, y, w, _ = rect
    alpha = band.getchannel("A")
    above = alpha.crop((0, 0, 480, y - feather + 1))
    past = alpha.crop((min(480, x + w + feather - 1), 0, 480, 720))
    return above.getbbox() is None and past.getbbox() is None


if __name__ == "__main__":
    main()
