# author: realcopacetic
"""
Shared mapping → substitution expansion.

Used by both the build-time BaseBuilder (with optional per-template items
for cartesian product) and the runtime resolver layer (no-items case).
"""

import re
from itertools import product
from typing import Any, Mapping

from resources.lib.shared.utilities import evaluate_expression


def inject_metadata(metadata: dict, substitutions: dict, *keys: str) -> dict:
    """
    Layer metadata for the given keys onto a substitution dict.

    :param metadata: Mapping-level metadata dict (item → fields).
    :param substitutions: Substitution dict to layer onto.
    :param keys: Item keys whose metadata should be merged in order.
    :return: New dict with metadata fields below substitutions.
    """
    combined: dict = {}
    for k in keys:
        combined.update(metadata.get(k, {}))
    return {**combined, **substitutions}


def enumerate_mapping_subs(
    mapping: dict,
    items: list | None = None,
    dynamic_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Enumerate substitution dicts for a mapping's loop values, optionally
    cartesian-producted with per-template items.

    :param mapping: Mapping definition (items, placeholders, metadata).
    :param items: Optional per-template values for cross-product.
    :param dynamic_key: Placeholder name for the per-template item value.
    :return: List of substitution dicts; ``[{}]`` when no loop values.
    """
    loop_values = mapping.get("items")
    placeholders = mapping.get("placeholders", {})
    metadata = mapping.get("metadata", {})
    key_name = placeholders.get("key", "")
    value_name = placeholders.get("value", "")
    cross = bool(items and dynamic_key)

    if isinstance(loop_values, dict):
        if cross:
            return [
                inject_metadata(
                    metadata,
                    {key_name: outer, value_name: inner, dynamic_key: item},
                    outer,
                    inner,
                )
                for outer, inner_values in loop_values.items()
                for inner, item in product(inner_values, items)
            ]
        return [
            inject_metadata(
                metadata, {key_name: outer, value_name: inner}, outer, inner
            )
            for outer, inner_values in loop_values.items()
            for inner in inner_values
        ]

    if isinstance(loop_values, list):
        if cross:
            return [
                inject_metadata(metadata, {key_name: lv, dynamic_key: item}, lv)
                for lv, item in product(loop_values, items)
            ]
        return [inject_metadata(metadata, {key_name: lv}, lv) for lv in loop_values]

    if cross:
        return [{dynamic_key: item} for item in items]

    return [{}]


class TokenError(KeyError):
    """A token could not be resolved in a loud context."""


_FOREIGN_PATTERN = re.compile(r"^@(\w+):(.+)\.(\w+)$")


def _match_brace(text: str, start: int) -> int:
    """
    Find the index of the brace matching ``text[start]``.

    :param text: Text being scanned.
    :param start: Index of an opening brace.
    :return: Index of the matching close brace, or -1 if unbalanced.
    """
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def resolve_foreign(key: str, registry: dict | None, context: str = "") -> str:
    """
    Resolve an ``@mapping:item.field`` metadata reference. Always loud.

    :param key: Token body including the leading ``@``.
    :param registry: Whole-mapping registry.
    :param context: Error-message suffix identifying the caller.
    :return: The referenced metadata value.
    """
    match = _FOREIGN_PATTERN.match(key)
    if not match:
        raise TokenError(f"malformed foreign reference '{{{key}}}'{context}")
    mapping, item, field = match.groups()
    if registry is None:
        raise TokenError(f"'{{{key}}}' used where no registry is available{context}")
    if mapping not in registry:
        raise TokenError(f"unknown mapping '{mapping}' in '{{{key}}}'{context}")
    meta = registry[mapping].get("metadata", {})
    if item not in meta:
        raise TokenError(f"unknown item '{item}' in '{{{key}}}'{context}")
    if field not in meta[item]:
        raise TokenError(f"unknown field '{field}' in '{{{key}}}'{context}")
    value = meta[item][field]
    if not isinstance(value, str):
        raise TokenError(f"non-string field '{field}' in '{{{key}}}'{context}")
    return value


def _resolve_key(
    key: str,
    tokens: Mapping[str, Any],
    mode: str,
    registry: dict | None,
    context: str,
) -> str:
    """
    Resolve one flat token body per the strictness policy.

    :param key: Token body with inner tokens already rendered.
    :param tokens: Local substitution values.
    :param mode: 'value' (unknown → ''), 'name' (loud), 'leave' (kept intact).
    :param registry: Registry for foreign references.
    :param context: Error-message suffix.
    :return: Resolved text.
    """
    if key.startswith("@"):
        return resolve_foreign(key, registry, context)
    if key in tokens:
        return tokens[key]
    result = evaluate_expression(key, tokens)
    if result is not None:
        return result
    if mode == "name":
        raise TokenError(f"unknown token '{{{key}}}'{context}")
    if mode == "leave":
        return "{" + key + "}"
    return ""


def render(
    text: str,
    tokens: Mapping[str, Any],
    *,
    mode: str = "value",
    registry: dict | None = None,
    context: str = "",
) -> str:
    """
    Substitute ``{tokens}`` with balanced-brace scanning, innermost first.

    :param text: Template text.
    :param tokens: Local substitution values.
    :param mode: Strictness for unknown tokens — see ``_resolve_key``.
    :param registry: Registry for ``@`` foreign references (always loud).
    :param context: Error-message suffix identifying the caller.
    :return: Rendered text.
    """
    out = []
    i = 0
    while i < len(text):
        start = text.find("{", i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        end = _match_brace(text, start)
        if end == -1:
            out.append(text[start:])
            break
        inner = render(
            text[start + 1 : end], tokens, mode=mode, registry=registry, context=context
        )
        out.append(_resolve_key(inner, tokens, mode, registry, context))
        i = end + 1
    return "".join(out)


def token_words(text: str) -> list[str]:
    """
    Collect word tokens appearing inside any ``{…}`` region, nesting included.

    :param text: Template text.
    :return: Words found inside brace regions.
    """
    words: list[str] = []
    i = 0
    while i < len(text):
        start = text.find("{", i)
        if start == -1:
            break
        end = _match_brace(text, start)
        if end == -1:
            break
        words.extend(re.findall(r"\w+", text[start + 1 : end]))
        i = end + 1
    return words
