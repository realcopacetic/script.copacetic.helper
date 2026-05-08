# author: realcopacetic
"""
Template loading and caching for the resolver layer.

The build pipeline writes a consolidated cache to disk after a successful
build. The Dynamic Editor reads it on open instead of walking source
folders. Falls back to source on cache miss.
"""

from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import RESOLVER_CACHE


def load_template_data(base_folder: str) -> tuple[dict, dict, dict]:
    """
    Load merged mappings, configs, and controls templates. Reads from the
    consolidated resolver cache when present; falls back to walking source
    folders. Used by the Dynamic Editor and any other read-side caller.

    :param base_folder: Skin extras builders folder root.
    :return: (mappings, configs_data, controls_data) as nested dicts.
    """
    handler = JSONHandler(RESOLVER_CACHE)
    if handler.exists:
        cache = next(iter(handler.data.values()), {})
        return (
            cache.get("mappings", {}),
            cache.get("configs", {}),
            cache.get("controls", {}),
        )
    return load_template_data_from_source(base_folder)


def load_template_data_from_source(base_folder: str) -> tuple[dict, dict, dict]:
    """
    Walk source template folders directly. Used by the build pipeline (which
    writes a fresh cache after) and as the cache-miss fallback.

    :param base_folder: Skin extras builders folder root.
    :return: (mappings, configs_data, controls_data) as nested dicts.
    """
    from resources.lib.builders.builder_config import BUILDER_MAPPINGS

    mappings_merger = JSONMerger(
        base_folder=base_folder, subfolders=["mappings"], grouping_key=None
    )
    mappings = {**BUILDER_MAPPINGS, **dict(mappings_merger.yield_merged_data())}

    configs_data: dict = {}
    configs_merger = JSONMerger(
        base_folder=base_folder, subfolders=["configs"], grouping_key="mapping"
    )
    for mapping_name, content in configs_merger.yield_merged_data():
        configs_data.setdefault(mapping_name, {}).update(content.get("configs") or {})

    controls_data: dict = {}
    controls_merger = JSONMerger(
        base_folder=base_folder, subfolders=["controls"], grouping_key="mapping"
    )
    for mapping_name, content in controls_merger.yield_merged_data():
        controls_data.setdefault(mapping_name, {}).update(
            content.get("controls") or {}
        )

    return mappings, configs_data, controls_data


def write_template_cache(
    mappings: dict, configs_data: dict, controls_data: dict
) -> None:
    """
    Write the consolidated template cache to disk for fast editor startup.

    :param mappings: Merged mappings dict (built-in + custom).
    :param configs_data: {mapping_name: {tpl_name: tpl_data}}.
    :param controls_data: {mapping_name: {tpl_name: tpl_data}}.
    """
    JSONHandler(RESOLVER_CACHE).write_json(
        {
            "mappings": mappings,
            "configs": configs_data,
            "controls": controls_data,
        }
    )
    log.debug(f"write_template_cache: cache written to {RESOLVER_CACHE}")
