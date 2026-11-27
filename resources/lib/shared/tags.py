# author: realcopacetic

"""
A song file's embedded lyrics, from tags Kodi's own loader reads them from
(music/tags/TagLoaderTagLib.cpp): an ID3v2 USLT frame (MP3), a LYRICS Vorbis comment
(FLAC, Ogg Vorbis, Opus, Ogg FLAC) and an APEv2 Lyrics item (Monkey's Audio, WavPack,
Musepack). Kodi fills a song's only at play.
"""

from collections.abc import Callable

import xbmcvfs

ID3 = 10  # bytes: an ID3v2 tag's header, and its footer
ID3V1 = 128  # bytes: an ID3v1 tag, last in the file
APE = 32  # bytes: an APEv2 tag's footer
APE_MARKS = (b"MAC ", b"wvpk", b"MPCK", b"MP+")  # Monkey's, WavPack, Musepack 8, 7
# ID3v2's text encodings by their byte: Latin-1, UTF-16 with a byte order mark,
# UTF-16 big-endian, UTF-8
ENCODINGS = ("latin-1", "utf-16", "utf-16-be", "utf-8")
MAX_TAG = 1 << 20  # bytes of an Ogg comment or APE tag read at most: lyrics are small
OGG = 27  # bytes: an Ogg page's header, ahead of its segment table
# The comment packet's mark: Vorbis, Opus, Ogg FLAC (a VORBIS_COMMENT block's header)
XIPH_MARKS = {b"\x03vorbis": 7, b"OpusTags": 8, b"\x04": 4, b"\x84": 4}
VORBIS_COMMENT = 4  # a FLAC metadata block's type
Read = Callable[[int, int], bytes]  # (position, size) -> the bytes there


def lyrics(path: str) -> str:
    """
    A song file's embedded lyrics. An MP3's and a FLAC's art is skipped unread; an
    Ogg comment or APE tag is read up to MAX_TAG, so lyrics behind more art are missed.

    :param path: The file, as Kodi's library holds it (smb:// and nfs:// too).
    :return: The text; "" for none, or a format Kodi reads no lyrics from.
    """
    with xbmcvfs.File(path) as file:

        def read(pos: int, size: int) -> bytes:
            file.seek(pos, 0)
            return bytes(file.readBytes(size)) if size else b""  # 0 reads the rest

        head, start = read(0, ID3), 0
        if head[:3] == b"ID3":  # an MP3's tag, or one ahead of a FLAC stream
            start = ID3 + _syncsafe(head[6:10]) + (ID3 if head[5] & 0x10 else 0)
            if read(start, 4) != b"fLaC":
                return _id3(read, head)
        elif head[:4] == b"OggS":
            return _ogg(read)
        elif head.startswith(APE_MARKS):
            return _ape(read, file.size())
        elif head[:4] != b"fLaC":
            return ""
        return _flac(read, start + 4)


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


def _id3(read: Read, head: bytes) -> str:
    """
    The last USLT frame's text (ULT in v2.2), as Kodi keeps, frame by frame through
    the tag; a compressed or encrypted frame is passed over.

    :param read: Reads the file.
    :param head: The tag's header.
    :return: The text; "" for none.
    """
    version, flags, end = head[3], head[5], ID3 + _syncsafe(head[6:10])
    if version < 4 and flags & 0x80:  # the whole tag unsynchronised: undone in memory
        data = bytes(ID3) + read(ID3, end - ID3).replace(b"\xff\x00", b"\xff")
        read, end = (lambda pos, size: data[pos : pos + size]), len(data)
    pos = ID3
    if flags & 0x40:  # an extended header: v2.4's size counts itself, v2.3's doesn't
        size = read(pos, 4)
        pos += _syncsafe(size) if version == 4 else 4 + int.from_bytes(size, "big")
    # v2.2's frames: a 3-letter name and 3-byte size; later ones 4 and 4, then 2 flags
    name, header = (b"USLT", 10) if version > 2 else (b"ULT", 6)
    # v2.4's flags: grouping 0x40, compressed 0x08, encrypted 0x04, unsynchronised
    # 0x02, data length 0x01; v2.3's: compressed 0x80, encrypted 0x40, grouping 0x20
    skipped, grouped = (0x0C, 0x40) if version == 4 else (0xC0, 0x20)
    found = ""
    while pos + header <= end:
        frame = read(pos, header)
        if frame[:1] in (b"", b"\0"):
            break  # the padding after the last frame, or the file's end
        field = frame[len(name) : len(name) * 2]
        size = _syncsafe(field) if version == 4 else int.from_bytes(field, "big")
        status = frame[9] if version > 2 else 0
        if frame[: len(name)] == name and not status & skipped:
            # A grouping byte, then v2.4's data length, ahead of the text
            ahead = bool(status & grouped) + (4 if version == 4 and status & 1 else 0)
            body = read(pos + header, size)[ahead:]
            if version == 4 and status & 0x02:
                body = body.replace(b"\xff\x00", b"\xff")
            found = _uslt(body)
        pos += header + size
    return found


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


def _flac(read: Read, pos: int) -> str:
    """
    The LYRICS comment of a FLAC stream's VORBIS_COMMENT block, block by block.

    :param read: Reads the file.
    :param pos: The first block's place, past the fLaC mark.
    :return: The text; "" for none.
    """
    last = False
    while not last:
        if len(block := read(pos, 4)) < 4:
            return ""
        last, kind = block[0] & 0x80, block[0] & 0x7F
        size = int.from_bytes(block[1:], "big")
        if kind == VORBIS_COMMENT:
            return _comment(read(pos + 4, size))
        pos += 4 + size
    return ""


def _ogg(read: Read) -> str:
    """
    The LYRICS comment of an Ogg file's second packet, gathered from its pages'
    segments, as TagLib reads it: whatever stream each page belongs to.

    :param read: Reads the file.
    :return: The text; "" for none.
    """
    pos, ended, packet = 0, False, bytearray()
    while len(page := read(pos, OGG + 255)) > OGG and page[:4] == b"OggS":
        lacing = page[OGG : OGG + page[26]]
        body = read(pos + OGG + len(lacing), sum(lacing))
        pos += OGG + len(lacing) + len(body)
        at = 0
        for size in lacing:
            packet += body[at : at + size]
            at += size
            if size == 255 and len(packet) < MAX_TAG:
                continue  # the packet goes on
            if ended:  # the comment, cut at MAX_TAG
                return next(
                    (
                        _comment(packet[skip:])
                        for mark, skip in XIPH_MARKS.items()
                        if packet.startswith(mark)
                    ),
                    "",
                )
            ended, packet = True, bytearray()
    return ""


def _ape(read: Read, end: int) -> str:
    """
    An APEv2 tag's last LYRICS item (its key in any case) as text, its first value,
    as TagLib finds the tag: at the file's end, ahead of an ID3v1 tag.

    :param read: Reads the file.
    :param end: The file's size.
    :return: The text; "" for none, or a binary item.
    """
    if end > ID3V1 and read(end - ID3V1, 3) == b"TAG":
        end -= ID3V1
    footer = read(max(end - APE, 0), APE)
    if footer[:8] != b"APETAGEX":
        return ""
    # the tag's size counts its items and footer, not a header ahead of them
    size, count = (int.from_bytes(footer[at : at + 4], "little") for at in (12, 16))
    if not APE < size <= end:
        return ""
    items, pos, found = read(end - size, min(size - APE, MAX_TAG)), 0, ""
    for _ in range(count):
        if (cut := items.find(b"\0", pos + 8)) < 0:
            break  # past the items read: a count too high, or the cut at MAX_TAG
        length = int.from_bytes(items[pos : pos + 4], "little")
        kind = items[pos + 4] & 0x06  # 0 text, 2 binary, 4 a link
        key, value = items[pos + 8 : cut], items[cut + 1 : cut + 1 + length]
        if len(value) < length:
            break  # cut at MAX_TAG: a part of lyrics would win over LRCLIB's
        pos = cut + 1 + length
        if key.upper() == b"LYRICS":  # TagLib keeps the last of a key
            found = "" if kind else value.partition(b"\0")[0].decode("utf-8", "replace")
    return found


def _comment(block: bytes) -> str:
    """
    A Vorbis comment block's LYRICS field, its name in any case, as Xiph's.

    :param block: The block's data: vendor, count, then length-prefixed fields.
    :return: The text; "" for none.
    """
    pos = 4 + int.from_bytes(block[:4], "little")
    count = int.from_bytes(block[pos : pos + 4], "little")
    pos += 4
    for _ in range(min(count, (len(block) - pos) // 4)):  # a field takes 4 at least
        size = int.from_bytes(block[pos : pos + 4], "little")
        field = block[pos + 4 : pos + 4 + size]
        if len(field) < size:
            break  # cut at MAX_TAG: a part of lyrics would win over LRCLIB's
        pos += 4 + size
        key, _, value = field.partition(b"=")
        if key.upper() == b"LYRICS":
            return value.decode("utf-8", "replace")
    return ""
