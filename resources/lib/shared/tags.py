# author: realcopacetic

"""
A song file's embedded lyrics, read from the tags Kodi's own loader reads them from
(music/tags/TagLoaderTagLib.cpp): an ID3v2 USLT frame (MP3) and a FLAC file's LYRICS
comment. Kodi fills a song's lyrics only at play, so another song's are read here.
"""

import xbmcvfs

ID3 = 10  # bytes: an ID3v2 tag's header
# ID3v2's text encodings by their byte: Latin-1, UTF-16 with a byte order mark,
# UTF-16 big-endian, UTF-8
ENCODINGS = ("latin-1", "utf-16", "utf-16-be", "utf-8")
VORBIS_COMMENT = 4  # a FLAC metadata block's type


def lyrics(path: str) -> str:
    """
    A song file's embedded lyrics; art and other frames are skipped, not read.

    :param path: The file, as Kodi's library holds it (smb:// and nfs:// too).
    :return: The text; "" for none, or a format Kodi reads no lyrics from.
    """
    with xbmcvfs.File(path) as file:
        head = bytes(file.readBytes(ID3))
        if head[:3] == b"ID3":
            return _id3(file, head)
        if head[:4] == b"fLaC":
            return _flac(file)
    return ""


def _syncsafe(data: bytes) -> int:
    """
    An ID3v2 size: big-endian bytes of seven bits each.

    :param data: The bytes.
    :return: The size.
    """
    size = 0
    for byte in data:
        size = size << 7 | byte & 0x7F
    return size


def _id3(file: xbmcvfs.File, head: bytes) -> str:
    """
    The first USLT frame's text (ULT in v2.2), frame by frame through the tag. A
    compressed or encrypted frame reads as none.

    :param file: The file.
    :param head: The tag's header.
    :return: The text; "" for none.
    """
    version, flags, end = head[3], head[5], ID3 + _syncsafe(head[6:10])
    pos = ID3
    if flags & 0x40:  # an extended header: v2.4's size counts itself, v2.3's doesn't
        size = bytes(file.readBytes(4))
        pos += _syncsafe(size) if version == 4 else 4 + int.from_bytes(size, "big")
    # v2.2's frames: a 3-letter name and 3-byte size; later ones 4 and 4, then 2 flags
    name, header = (b"USLT", 10) if version > 2 else (b"ULT", 6)
    while pos + header <= end:
        file.seek(pos, 0)
        frame = bytes(file.readBytes(header))
        if frame[:1] in (b"", b"\0"):
            return ""  # the padding after the last frame, or the file's end
        field = frame[len(name) : len(name) * 2]
        size = _syncsafe(field) if version == 4 else int.from_bytes(field, "big")
        pos += header + size
        if frame[: len(name)] != name:
            continue
        status = frame[9] if version > 2 else 0
        if status & (0x0C if version == 4 else 0xC0):
            return ""
        body = bytes(file.readBytes(size))
        if version == 4 and status & 0x01:  # a data length ahead of the text
            body = body[4:]
        # Unsynchronised: v2.4 marks each frame, v2.3 the whole tag
        unsynced = status & 0x02 if version == 4 else flags & 0x80
        if unsynced:
            body = body.replace(b"\xff\x00", b"\xff")
        return _uslt(body)
    return ""


def _uslt(body: bytes) -> str:
    """
    A USLT frame's text: its encoding byte, language and description come first.

    :param body: The frame's data.
    :return: The text; "" for none.
    """
    encoding, rest = body[:1], body[4:]
    wide = encoding in (b"\x01", b"\x02")  # UTF-16: a two-byte terminator, aligned
    step = 2 if wide else 1
    cut = next(
        (
            i
            for i in range(0, len(rest) - step + 1, step)
            if not any(rest[i : i + step])
        ),
        len(rest),
    )
    return rest[cut + step :].decode(ENCODINGS[encoding[0]], "replace").strip("\0")


def _flac(file: xbmcvfs.File) -> str:
    """
    The LYRICS comment of a FLAC file's VORBIS_COMMENT block, block by block.

    :param file: The file, read past its fLaC mark.
    :return: The text; "" for none.
    """
    pos, last = 4, False
    while not last:
        file.seek(pos, 0)
        if len(block := bytes(file.readBytes(4))) < 4:
            return ""
        last, kind = block[0] & 0x80, block[0] & 0x7F
        size = int.from_bytes(block[1:], "big")
        if kind == VORBIS_COMMENT:
            return _comment(bytes(file.readBytes(size)))
        pos += 4 + size
    return ""


def _comment(block: bytes) -> str:
    """
    A Vorbis comment block's LYRICS field, its name in any case, as Xiph's.

    :param block: The block's data: vendor, count, then length-prefixed fields.
    :return: The text; "" for none.
    """
    pos = 4 + int.from_bytes(block[:4], "little")
    count = int.from_bytes(block[pos : pos + 4], "little")
    pos += 4
    for _ in range(count):
        size = int.from_bytes(block[pos : pos + 4], "little")
        field = block[pos + 4 : pos + 4 + size]
        pos += 4 + size
        key, _, value = field.partition(b"=")
        if key.upper() == b"LYRICS":
            return value.decode("utf-8", "replace")
    return ""
