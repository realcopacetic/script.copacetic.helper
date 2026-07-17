# author: realcopacetic
"""
Shared mapping → substitution expansion.

Used by both the build-time BaseBuilder (with optional per-template items
for cartesian product) and the runtime resolver layer (no-items case).
"""

from itertools import product
from typing import Any


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
