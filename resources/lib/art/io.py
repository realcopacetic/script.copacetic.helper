# author: realcopacetic

import xbmcvfs
from PIL import Image

from resources.lib.art.policy import ColorConfig


def write_image(path: str, image: Image.Image, fmt: str, cfg: ColorConfig) -> None:
    """
    Write a PIL image to a VFS path using configured JPEG/PNG settings.

    :param path: Destination VFS path.
    :param image: PIL image to save.
    :param fmt: "JPEG" or "PNG".
    :param cfg: Colour/encode configuration.
    """
    with xbmcvfs.File(path, "wb") as fh:
        if fmt == "JPEG":
            image.save(
                fh,
                "JPEG",
                quality=cfg.jpeg_quality,
                optimize=cfg.jpeg_optimize,
                progressive=cfg.jpeg_progressive,
                subsampling=cfg.jpeg_subsampling,
            )
        else:
            image.save(
                fh,
                "PNG",
                optimize=cfg.png_optimize,
                compress_level=cfg.png_compress_level,
            )