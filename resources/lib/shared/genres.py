# author: realcopacetic
"""
Music genre buckets: a skin's genre icons and the daily mixes' cards. A genre's
bucket is the first row with a term found in it (lower case): EXCEPTIONS, then
KEYWORDS.
"""

from functools import cache

# Genres a later, shorter keyword would mis-file (dancehall and dance, rave hardcore
# and punk hardcore, wassoulou and soul): their bucket, or None for the fallback
EXCEPTIONS: tuple[tuple[str | None, tuple[str, ...]], ...] = (
    ("Reggae", ("dancehall", "dance hall")),
    ("Country", ("country dance",)),
    ("Blues", ("piedmont",)),
    ("HipHop", ("hardcore hip hop", "hardcore hip-hop", "hardcore rap")),
    ("Bass", ("breakbeat hardcore", "hardcore breaks")),
    (
        "Electronic",
        (
            "digital hardcore",
            "freeform hardcore",
            "happy hardcore",
            "hardcore techno",
            "uk hardcore",
            "uptempo hardcore",
        ),
    ),
    ("World", ("afroswing", "wassoulou")),
    (
        None,
        (
            "aktorska",
            "ambasse bey",
            "avtorskaya",
            "boduberu",
            "bosanska",
            "demostyle",
            "diskan",
            "euskal kantagintza",
            "frapcore",
            "graphical sound",
            "maskanda",
            "sasscore",
        ),
    ),
)
# Each bucket's keywords; narrow buckets before the broad one they split from (Blues
# before Rock, Techno before Electronic), Rock and Pop near the end as the broadest
KEYWORDS: dict[str, tuple[str, ...]] = {
    "Christmas": ("christmas", "xmas", "holiday"),
    "Kids": ("children", "kids", "lullab", "nursery"),
    "SpokenWord": (
        "spoken",
        "audiobook",
        "poetry",
        "podcast",
        "audio drama",
        "radio play",
        "speech",
    ),
    "Comedy": ("comedy", "novelty", "parody", "humo"),
    "VideoGame": ("video game", "chiptune", "vgm", "8-bit"),
    "Musical": (
        "musical",
        "show tune",
        "showtune",
        "broadway",
        "cabaret",
        "rock opera",
        "cast recording",
    ),
    "Soundtrack": ("soundtrack", "score", "film", "stage & screen", "anime"),
    "Metal": ("metal", "deathcore", "grindcore", "djent"),
    "Industrial": ("industrial", "ebm", "power electronics"),
    "Goth": ("goth", "darkwave", "dark wave", "deathrock", "coldwave"),
    "Hardcore": ("hardcore",),
    "Emo": ("emo",),
    "Punk": ("punk",),
    "Gospel": ("gospel", "christian", "worship", "hymn"),
    "Synth": ("synth", "new wave"),
    "LoFi": ("lo-fi", "lofi", "chill", "downtempo", "trip hop", "trip-hop", "triphop"),
    "Trance": ("trance", "goa"),
    "Techno": ("techno",),
    "Bass": (
        "drum and bass",
        "drum & bass",
        "dnb",
        "dubstep",
        "jungle",
        "breakbeat",
        "neurofunk",
        "liquid funk",
        "drumfunk",
        "drumstep",
        "uk garage",
        "future garage",
        "speed garage",
        "dark garage",
        "2-step",
        "breaks",
        "bass",
    ),
    "Disco": ("disco",),
    "Ambient": ("ambient", "drone"),
    "NewAge": ("new age", "meditation", "healing", "relaxation"),
    "Electronic": (
        "electro",
        "house",
        "dance",
        "edm",
        "idm",
        "hardstyle",
        "big beat",
        "glitch",
        "footwork",
    ),
    "HipHop": ("hip hop", "hip-hop", "hiphop", "rap", "grime", "drill"),
    "Latin": (
        "latin",
        "salsa",
        "bossa",
        "samba",
        "reggaeton",
        "cumbia",
        "tango",
        "flamenco",
        "bachata",
        "merengue",
        "mpb",
        "forró",
    ),
    "Reggae": ("reggae", "rocksteady", "lovers rock", "ragga", "dub"),
    "Ska": ("ska",),
    "Funk": ("funk",),
    "Soul": ("soul", "r&b", "rhythm and blues", "rhythm & blues", "motown", "new jack"),
    "Blues": ("blues",),
    "Lounge": ("lounge", "easy listening", "exotica"),
    "Jazz": ("jazz", "swing", "bop", "big band"),
    "Celtic": ("celtic", "irish", "scottish", "gaelic"),
    "Country": ("country", "bluegrass", "honky tonk"),
    "Americana": ("americana", "roots", "heartland"),
    "SingerSongwriter": ("singer",),
    "Folk": ("folk", "acoustic"),
    "Indie": ("indie", "shoegaz", "dream pop", "britpop", "baroque pop"),
    "Psychedelic": ("psychedel",),
    "Prog": ("progressive", "prog", "art rock", "kraut"),
    "PostRock": ("post-rock", "post rock", "math rock", "slowcore"),
    "Alternative": ("alternative", "grunge"),
    "Rock": ("rock",),
    "Experimental": ("experimental", "avant-garde", "noise", "musique concr"),
    "Classical": (
        "classical",
        "baroque",
        "opera",
        "orchestral",
        "symphon",
        "choral",
        "chamber music",
    ),
    "World": (
        "world",
        "afro",
        "african",
        "highlife",
        "indian",
        "carnatic",
        "hindustani",
    ),
    "Pop": ("pop",),
}


def rows() -> list[tuple[str | None, tuple[str, ...]]]:
    """
    Every row in the order a genre is tried: EXCEPTIONS, then KEYWORDS.

    :return: (bucket, terms) pairs.
    """
    return [*EXCEPTIONS, *KEYWORDS.items()]


@cache
def genre_bucket(genre: str) -> str | None:
    """
    A genre's bucket, as the skin's icon rows pick it: a tag, or a whole
    ListItem.Genre ("Indie Rock / Alternative": the first row found in any).

    :param genre: Genre text.
    :return: Bucket name; None for none.
    """
    text = genre.lower()
    return next((b for b, terms in _ROWS if any(t in text for t in terms)), None)


def genre_mapping() -> dict:
    """
    The builder's music_genres mapping: every row's terms in order, each with its
    bucket (genre_bucket metadata, "none" for the fallback), for a skin's icon rows.

    :return: Static mapping definition.
    """
    pairs = [(term, bucket or "none") for bucket, terms in _ROWS for term in terms]
    return {
        "mode": "static",
        "items": [term for term, _ in pairs],
        "metadata": {term: {"genre_bucket": bucket} for term, bucket in pairs},
        "placeholders": {"key": "genre_keyword"},
    }


_ROWS = rows()
