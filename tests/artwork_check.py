"""
Run the artwork pipeline (prepare, then compose) on synthetic posters outside Kodi.

Checks the label's measured rect (lines, widest line), the element-on-art step, its
winning colour, the band's PNG and alpha (solid over the label's lines, 0 a feather
away) and, at step 3, that the tinted band reads at the ratio; prints each serve's
time. Needs Pillow and the skin (its Font.xml and fonts measure the label); no network.

    python tests/artwork_check.py ../skin.copacetic2
"""

import os
import random
import shutil
import sys
import tempfile
import time
import zlib
from pathlib import Path

from build_offline import HELPER, install_stubs
from PIL import Image, ImageChops, ImageDraw, ImageFont

ImageFont.LAYOUT_BASIC = ImageFont.Layout.BASIC  # Kodi's Pillow (8.4, 9.0) name

GHOSTED, GUNMETAL = "fff0efef", "ff312124"
STRIP = {
    "icon_blur": "true",
    "icon_blur_radius": "4",
    "icon_darken": "true",
    "icon_darken_rects": "20,589,440,111",  # the typewriter's text box, 3 lines
    "icon_darken_frame": "480,720",
    "icon_darken_label": "Mission Impossible Dead",
    "icon_darken_label_font": "description_l",
    "icon_darken_label_pitch": "-37",
    "icon_element_colors": f"{GHOSTED},{GUNMETAL}",
}


def noise(img: Image.Image, _: ImageDraw.ImageDraw) -> None:
    """Fill the poster with random colour noise: busy, mid-grey once blurred."""
    rng = random.Random(1)
    img.putdata([tuple(rng.randrange(256) for _ in "rgb") for _ in range(480 * 720)])


LABELS = {  # label: its rect in the strip poster's text box, one to three lines
    "Up •\xa02009": (20, 663, 146, 37),
    "Radiohead • OK Computer •\xa01997": (20, 626, 372, 74),  # "• 1997" holds
    "Mission: Impossible – Dead Reckoning Part One •\xa02023": (20, 626, 384, 74),
    "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb "
    "•\xa01964": (20, 589, 437, 111),
    "Borat: Cultural Learnings of America for Make Benefit Glorious Nation of "
    "Kazakhstan •\xa02006": (
        20,
        589,
        429,
        111,
    ),  # four lines, capped at the box's three
    "Supercalifragilisticexpialidociousness •\xa02000": (20, 626, 434, 74),  # cut
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
    vfs.File = open
    sys.path.insert(0, str(HELPER))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="artwork-check-"))
    install(tmp, Path(sys.argv[1]).resolve())
    from resources.lib.art.analyzer import ColorAnalyzer
    from resources.lib.art.color import contrast, from_hex, luminance
    from resources.lib.art.darken import ColorDarken
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
    shutil.rmtree(tmp)
    sys.exit(bool(failures))


def solid(band: Image.Image, rect: tuple[int, int, int, int]) -> bool:
    """
    The band's alpha is full over the label's lines across the whole text box
    (frame px are blur px).

    :param band: The band, RGBA.
    :param rect: The label's measured rect.
    :return: True when every pixel there is opaque.
    """
    bx, _, bw, _ = map(int, STRIP["icon_darken_rects"].split(","))
    box = (bx, rect[1], bx + bw, rect[1] + rect[3])
    return band.getchannel("A").crop(box).getextrema() == (255, 255)


def clear(band: Image.Image, rect: tuple[int, int, int, int], feather: int) -> bool:
    """
    The band's alpha is 0 a feather above the label's lines, and so above it.

    :param band: The band, RGBA.
    :param rect: The label's measured rect.
    :param feather: The band's feather, frame px.
    :return: True when the rows from there up are clear.
    """
    return (
        band.getchannel("A").crop((0, 0, 480, rect[1] - feather + 1)).getbbox() is None
    )


if __name__ == "__main__":
    main()
