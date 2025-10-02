# author: realcopacetic

from typing import Iterable, Iterator
import re
import urllib.parse as urllib


_PLUGIN_KV = re.compile(r"([A-Za-z0-9_.%-]+)=(.*?)(?=&[A-Za-z0-9_.%-]+=|$)")
"""Extract k=v where value runs up to the next &KEY= or end; preserves raw '&' in values."""


def parse_params(argv: list[str], mode: str = "plugin") -> dict[str, str]:
    """
    Unified argv parser for Kodi plugin + script entry points.
    - Plugin URLs may contain raw '&' inside values.
    - RunScript splits on commas before Python sees argv, so values with commas
      arrive as multiple tokens and must be stitched.

    :param argv: ***
    :param mode: ***
    :return: ***
    """
    return parse_plugin_argv(argv) if mode == "plugin" else parse_script_argv(argv)


def parse_plugin_argv(argv: list[str]) -> dict[str, str]:
    """
    Parse plugin argv. Accepts '?k=v&k=v' or 'k=v&k=v' in argv[2].
    Preserves raw '&' inside values by splitting only at '&KEY='.

    :param argv: 'argv[2]' querystring to be parsed via tolerant regex
    :return: ***
    """
    q = ""
    if len(argv) >= 3 and argv[2]:
        q = argv[2][1:] if argv[2].startswith("?") else argv[2]
    if not q:
        return {}
    q = q.replace("&amp;", "&")
    return {k: urllib.unquote(v) for k, v in _PLUGIN_KV.findall(q)}


def parse_script_argv(argv: list[str]) -> dict[str, str]:
    """
    Kodi passes argv[1:] as tokens split on commas. If a value contains commas,
    Kodi has already split it into multiple tokens; tokens without '=' are value
    fragments. We stitch them back onto the previous key's value.

    :param argv: 'argv[1:]' list of tokens
    :return: ***
    """
    return {k: urllib.unquote(v) for k, v in _iter_script_pairs(argv[1:])}


def _iter_script_pairs(tokens: Iterable[str]) -> Iterator[tuple[str, str]]:
    """
    Yield (key, value) pairs from RunScript tokens, stitching comma fragments.
    ['action=foo', 'name=Greatest Hits', ' Vol. 2']  →  ('name', 'Greatest Hits, Vol. 2')
    """
    cur_key = None
    cur_val = ""
    for tok in tokens:
        if not tok:
            continue
        if "=" in tok:
            if cur_key is not None:
                yield cur_key, cur_val
            cur_key, cur_val = tok.split("=", 1)
        else:
            if cur_key is not None:
                cur_val = f"{cur_val},{tok}"
    if cur_key is not None:
        yield cur_key, cur_val
