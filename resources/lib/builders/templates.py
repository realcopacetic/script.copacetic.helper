# author: realcopacetic
"""
Template loading and caching for the resolver layer.

The build pipeline writes a consolidated cache to disk after a successful
build. The Dynamic Editor reads it on open instead of walking source
folders. Falls back to source on cache miss.
"""

from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import (
    ADDON,
    RESOLVER_CACHE,
    skin_id,
    skin_path,
    skin_version,
)

_CACHE_VERSION = "1"


def cache_stamp() -> str:
    """
    Identity of the cache: schema version, the loaded skin's id and version (from
    its folder: lookandfeel.skin changes first on a switch), and the running helper's.

    :return: Stamp string, e.g. ``1/skin.copacetic2/2.0.1/1.1.13``.
    """
    skin = skin_path()
    helper = ADDON.getAddonInfo("version")
    return "/".join((_CACHE_VERSION, skin_id(skin), skin_version(skin), helper))


def cache_is_current(stamp: str) -> bool:
    """
    True when the resolver cache exists and matches ``stamp``.

    :param stamp: The check's cache_stamp(), read once so compare and write agree.
    :return: True when the stored stamp equals ``stamp``.
    """
    handler = JSONHandler(RESOLVER_CACHE)
    if not handler.exists:
        return False
    cache = next(iter(handler.data.values()), {})
    return cache.get("stamp") == stamp


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
        if cache.get("stamp") != cache_stamp():
            log.info(
                "load_template_data: resolver cache stamp mismatch — "
                "reading templates from source"
            )
            return load_template_data_from_source(base_folder)
        mappings = cache.get("mappings", {})
        configs_data = cache.get("configs", {})
        controls_data = cache.get("controls", {})
        return mappings, configs_data, controls_data
    return load_template_data_from_source(base_folder)


def load_template_data_from_source(base_folder: str) -> tuple[dict, dict, dict]:
    """
    Walk source template folders directly. Used by the build pipeline (which
    writes a fresh cache after) and as the cache-miss fallback.

    :param base_folder: Skin extras builders folder root.
    :return: (mappings, configs_data, controls_data) as nested dicts.
    """
    from resources.lib.builders.builder_config import (
        CONFIGS_FOLDER,
        CONTROLS_FOLDER,
        MAPPINGS_FOLDER,
    )

    mappings_merger = JSONMerger(
        base_folder=base_folder, subfolders=[MAPPINGS_FOLDER], grouping_key=None
    )
    mappings = dict(mappings_merger.yield_merged_data())

    configs_data = {}
    configs_merger = JSONMerger(
        base_folder=base_folder, subfolders=[CONFIGS_FOLDER], grouping_key="mapping"
    )
    for mapping_name, content in configs_merger.yield_merged_data():
        configs_data.setdefault(mapping_name, {}).update(content.get("configs") or {})

    controls_data = {}
    controls_merger = JSONMerger(
        base_folder=base_folder, subfolders=[CONTROLS_FOLDER], grouping_key="mapping"
    )
    for mapping_name, content in controls_merger.yield_merged_data():
        controls_data.setdefault(mapping_name, {}).update(content.get("controls") or {})

    return mappings, configs_data, controls_data


def write_template_cache(
    mappings: dict, configs_data: dict, controls_data: dict, stamp: str
) -> None:
    """
    Write the consolidated template cache to disk for fast editor startup.

    :param mappings: Merged mappings dict (built-in + custom).
    :param configs_data: {mapping_name: {tpl_name: tpl_data}}.
    :param controls_data: {mapping_name: {tpl_name: tpl_data}}.
    :param stamp: The build's cache_stamp().
    """
    JSONHandler(RESOLVER_CACHE).write_json(
        {
            "stamp": stamp,
            "mappings": mappings,
            "configs": configs_data,
            "controls": controls_data,
        }
    )
    log.debug(f"write_template_cache: cache written to {RESOLVER_CACHE}")
