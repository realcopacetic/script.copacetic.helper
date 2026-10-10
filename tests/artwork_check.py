"""
Run the artwork pipeline (prepare, then compose) on synthetic posters outside Kodi.

Checks the element-on-art step, its winning colour and, at step 3, that the tinted
band reads at the ratio; prints each serve's time. Needs Pillow; no network.
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
from PIL import Image, ImageDraw

GHOSTED, GUNMETAL = "fff0efef", "ff312124"
STRIP = {
    "icon_blur": "true",
    "icon_blur_radius": "4",
    "icon_darken": "true",
    "icon_darken_rects": "10,665,460,45",
    "icon_darken_frame": "480,720",
    "icon_darken_label": "Mission Impossible Dead",
    "icon_darken_label_px": "15",
    "icon_element_colors": f"{GHOSTED},{GUNMETAL}",
}
LABEL_RECT = "10,665,345,45"  # the rect clamped to the label: 23 characters x 15 px


def noise(img: Image.Image, _: ImageDraw.ImageDraw) -> None:
    """Fill the poster with random colour noise: busy, mid-grey once blurred."""
    rng = random.Random(1)
    img.putdata([tuple(rng.randrange(256) for _ in "rgb") for _ in range(480 * 720)])


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


def install(tmp: Path) -> None:
    """
    build_offline's stubs, plus the file calls the artwork cache makes.

    :param tmp: Scratch root: add-on data, texture cache and posters.
    """
    (tmp / "out" / "temp").mkdir(parents=True)
    install_stubs(HELPER, HELPER, tmp / "stage", tmp / "out", verbose=False)  # no skin
    xbmc, vfs = sys.modules["xbmc"], sys.modules["xbmcvfs"]
    special = vfs.translatePath
    xbmc.getCacheThumbName = lambda url: f"{zlib.crc32(url.encode()):08x}.tbn"
    vfs.translatePath = lambda p: special(p) if p.startswith("special://") else p
    vfs.exists = os.path.exists
    vfs.mkdirs = lambda p: os.makedirs(p, exist_ok=True) or True
    vfs.copy = lambda src, dst: bool(shutil.copy(src, dst))
    vfs.delete = lambda p: os.path.exists(p) and os.remove(p)
    vfs.File = open
    sys.path.insert(0, str(HELPER))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="artwork-check-"))
    install(tmp)
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
    failures = 0
    for name, (draw, step, winner, darken) in POSTERS.items():
        img = Image.new("RGB", (480, 720))
        draw(img, ImageDraw.Draw(img))
        img.save(path := str(tmp / f"{name}.jpg"), quality=95)
        art, cold = serve({"icon_url": path, **STRIP})
        again, warm = serve({"icon_url": path, **STRIP})
        band = art.get("icon_band", "")
        got = 3 if band and band != art["icon"] else 2 if band else 1
        note = ""
        ok = (got, art["icon_element_color"]) == (step, winner) and art == again
        if darken is not None:
            ok &= art["icon_darken"] == darken
        if got == 3:
            copy = Image.open(band).convert("RGB")
            box = engine.boxes(copy.size, LABEL_RECT, STRIP["icon_darken_frame"])[0]
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
    shutil.rmtree(tmp)
    sys.exit(bool(failures))


if __name__ == "__main__":
    main()
