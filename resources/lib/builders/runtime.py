# author: realcopacetic

import uuid
from typing import Iterator

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler, JSONMerger


def _enumerate_subs(mapping: dict) -> list[dict]:
    """
    Enumerate substitution dicts for a mapping with metadata layered on.
    Mirrors BaseBuilder.generate_substitutions for the no-item, no-index
    case; no loop-position flags are injected.

    :param mapping: Mapping definition.
    :return: List of substitution dicts.
    """
    loop_values = mapping.get("items")
    placeholders = mapping.get("placeholders", {})
    metadata = mapping.get("metadata", {})
    key_name = placeholders.get("key", "")
    value_name = placeholders.get("value", "")

    def _inject(sub: dict, *keys: str) -> dict:
        combined: dict = {}
        for k in keys:
            combined.update(metadata.get(k, {}))
        return {**combined, **sub}

    if isinstance(loop_values, dict):
        return [
            _inject({key_name: outer, value_name: inner}, outer, inner)
            for outer, inner_values in loop_values.items()
            for inner in inner_values
        ]
    if isinstance(loop_values, list):
        return [_inject({key_name: v}, v) for v in loop_values]
    return [{}]


class ConfigsResolver:
    """
    Resolves configs from source templates on demand, with caching.
    Replaces the build-time ConfigsBuilder + configs.json file.
    """

    def __init__(self, mappings: dict, base_folder: str) -> None:
        """
        Load source templates, build the reverse index, eagerly resolve
        every key once to surface malformed templates at startup.

        :param mappings: Dictionary of mapping definitions.
        :param base_folder: Skin extras builders folder containing configs/.
        """
        self._mappings = mappings
        self._rules = RuleEngine()
        self._templates = self._load_templates(base_folder)
        self._index = self._build_index()
        self._cache: dict[str, dict] = {}
        for cfg_key in self._index:
            try:
                self.resolve(cfg_key)
            except Exception as e:
                log.warning(
                    f"{self.__class__.__name__}: failed to resolve " f"'{cfg_key}': {e}"
                )

    def _load_templates(self, base_folder: str) -> dict:
        """
        Load all configs templates keyed by (mapping_name, template_name).

        :param base_folder: Builders folder root.
        :return: Mapping of (mapping_name, template_name) → template data.
        """
        merger = JSONMerger(
            base_folder=base_folder,
            subfolders=["configs"],
            grouping_key="mapping",
        )
        templates: dict = {}
        for mapping_name, content in merger.yield_merged_data():
            for tpl_name, tpl_data in (content.get("configs") or {}).items():
                templates[(mapping_name, tpl_name)] = tpl_data
        return templates

    def _build_index(self) -> dict:
        """
        Build reverse index resolved_cfg_key → (mapping_name, tpl_name, sub).
        Iterates every (template × substitution) without resolving rules.

        :return: Index mapping cfg keys to template + sub origin.
        """
        index: dict = {}
        for (mapping_name, tpl_name), _data in self._templates.items():
            for sub in _enumerate_subs(self._mappings.get(mapping_name, {})):
                try:
                    cfg_key = tpl_name.format(**sub)
                except KeyError as e:
                    log.debug(
                        f"{self.__class__.__name__}: template '{tpl_name}' "
                        f"in mapping '{mapping_name}' references unknown "
                        f"placeholder {e}; skipping for sub={sub}"
                    )
                    continue
                index[cfg_key] = (mapping_name, tpl_name, sub)
        return index

    def resolve(self, cfg_key: str) -> dict:
        """
        Resolve a single config entry by its fully-expanded key. Returns the
        same shape ConfigsBuilder previously wrote to configs.json.

        :param cfg_key: Resolved config key (e.g. "movies_layout").
        :return: Resolved entry dict, or empty dict if cfg_key is unknown.
        """
        if not cfg_key:
            return {}
        if cfg_key in self._cache:
            return self._cache[cfg_key]
        entry = self._index.get(cfg_key)
        if entry is None:
            return {}
        mapping_name, tpl_name, sub = entry
        result = self._resolve_one(
            self._templates[(mapping_name, tpl_name)], sub, mapping_name
        )
        self._cache[cfg_key] = result
        return result

    def iter_static_defaults(self) -> Iterator[tuple[str, str]]:
        """
        Yield (cfg_key, default) for every resolved static-mode entry that
        has a default. Used by initialize_skinstrings.

        :return: Iterator of (cfg_key, default_value) pairs.
        """
        for cfg_key in self._index:
            cfg = self.resolve(cfg_key)
            if cfg.get("mode") != "static":
                continue
            default = cfg.get("default")
            if default is not None:
                yield cfg_key, default

    def _resolve_one(self, data: dict, sub: dict, mapping_name: str) -> dict:
        """
        Resolve one template against one sub: filter items by rules, attach
        labels, choose a default. Same output shape as old resolve_values.

        :param data: Raw template data.
        :param sub: Substitution dict.
        :param mapping_name: Mapping owning this template.
        :return: Resolved entry dict.
        """
        defaults_data = {
            "items": [],
            "mode": "dynamic",
            "filter_mode": "exclude",
            "rules": [],
        }
        merged = {**defaults_data, **data}

        raw_items = merged["items"]
        if isinstance(raw_items, dict):
            items_list = list(raw_items.keys())
            labels = {k: v for k, v in raw_items.items() if v}
        else:
            items_list = raw_items
            labels = {}

        excluded = {
            value
            for rule in merged["rules"]
            if self._rules.evaluate(rule["condition"].format(**sub))
            for value in rule.get("value", [])
        }
        items = [
            item
            for item in items_list
            if (item not in excluded) == (merged["filter_mode"] == "exclude")
        ]

        out: dict = {"items": items, "mode": merged["mode"]}
        if labels:
            out["labels"] = labels

        defaults_map = data.get("defaults") or {}
        if defaults_map:
            mapping = self._mappings.get(mapping_name, {})
            default_key = data.get("default_key") or mapping.get(
                "placeholders", {}
            ).get("key")
            lookup = sub.get(default_key, "") if default_key else ""
            default_value = defaults_map.get(lookup) or defaults_map.get("*")
            if default_value not in items:
                default_value = items[0] if items else None
            if default_value is not None:
                out["default"] = default_value

        return out


class ControlsResolver:
    """
    Resolves controls from source templates on demand, cached per window.
    Replaces the build-time ControlsBuilder + controls.json file.
    """

    def __init__(self, mappings: dict, base_folder: str) -> None:
        """
        Load source controls templates via JSONMerger.

        :param mappings: Dictionary of mapping definitions.
        :param base_folder: Skin extras builders folder containing controls/.
        """
        self._mappings = mappings
        self._templates = self._load_templates(base_folder)
        self._cache: dict[str, dict] = {}

    def _load_templates(self, base_folder: str) -> list:
        """
        Load source controls templates as (mapping_name, tpl_name, data) tuples.

        :param base_folder: Builders folder root.
        :return: List of (mapping_name, template_name, template_data) tuples.
        """
        merger = JSONMerger(
            base_folder=base_folder,
            subfolders=["controls"],
            grouping_key="mapping",
        )
        templates: list = []
        for mapping_name, content in merger.yield_merged_data():
            for tpl_name, tpl_data in (content.get("controls") or {}).items():
                templates.append((mapping_name, tpl_name, tpl_data))
        return templates

    def for_window(self, xml_filename: str) -> dict:
        """
        Return resolved controls visible in the given window. Cached per window.

        :param xml_filename: Lowercase XML filename of the open editor window.
        :return: Mapping of resolved control name → resolved control dict.
        """
        if xml_filename in self._cache:
            return self._cache[xml_filename]
        resolved: dict = {}
        for mapping_name, tpl_name, tpl_data in self._templates:
            windows = tpl_data.get("window", [])
            if not any(w in xml_filename for w in windows):
                continue
            resolved.update(self._expand(mapping_name, tpl_name, tpl_data))
        self._cache[xml_filename] = resolved
        return resolved

    def _expand(self, mapping_name: str, template_name: str, data: dict) -> dict:
        """
        Expand one control template into resolved form(s). Dynamic-mode is
        passthrough; static contextual_bindings expand the bindings list;
        plain static templates expand template name and string fields.

        :param mapping_name: Mapping owning this template.
        :param template_name: Template control name.
        :param data: Template data dict.
        :return: Mapping of resolved name → resolved control dict.
        """
        if data.get("mode") == "dynamic":
            return {template_name: {"mapping": mapping_name, **data}}

        substitutions = _enumerate_subs(self._mappings.get(mapping_name, {}))

        if "contextual_bindings" in data:
            resolved_bindings: list = []
            seen: set = set()
            for sub in substitutions:
                resolved = {
                    k: (v.format(**sub) if isinstance(v, str) else v)
                    for k, v in data["contextual_bindings"].items()
                }
                key = tuple(sorted(resolved.items()))
                if key not in seen:
                    seen.add(key)
                    resolved_bindings.append(resolved)
            return {
                template_name: {
                    "mapping": mapping_name,
                    **{k: v for k, v in data.items() if k != "contextual_bindings"},
                    "contextual_bindings": resolved_bindings,
                }
            }

        return {
            template_name.format(**sub): {
                "mapping": mapping_name,
                **{
                    k: (v.format(**sub) if isinstance(v, str) else v)
                    for k, v in data.items()
                },
            }
            for sub in substitutions
        }


class RuntimeStateManager:
    """
    Manages runtime state in runtime_state.json plus configs and controls
    resolution from source templates. UUIDs provide stable, position-
    independent item identifiers.
    """

    def __init__(
        self, mappings: dict, base_folder: str, runtime_state_path: str
    ) -> None:
        """
        Initialise resolvers and runtime state handler.

        :param mappings: Dictionary containing all mappings.
        :param base_folder: Skin extras builders folder root.
        :param runtime_state_path: Path to runtime_state.json.
        """
        self._mappings = mappings
        self.configs = ConfigsResolver(mappings, base_folder)
        self.controls = ControlsResolver(mappings, base_folder)
        self._runtime_state_handler = JSONHandler(runtime_state_path)
        self._runtime_state_cache: dict | None = None

    @property
    def mappings(self) -> dict:
        """
        Retrieve merged mapping definitions.

        :return: Dict of mapping configurations.
        """
        return self._mappings

    def resolve_config(self, cfg_key: str | None) -> dict:
        """
        Resolve a config entry from source templates via the configs resolver.

        :param cfg_key: Resolved config key, or None.
        :return: Resolved config dict, empty dict if cfg_key is None or unknown.
        """
        return self.configs.resolve(cfg_key) if cfg_key else {}

    @property
    def runtime_state(self) -> dict:
        """
        Load and return the current runtime state. Cached in memory; cache
        is invalidated after writes.

        :return: Dict of mapping_key → list of state entries.
        """
        if self._runtime_state_cache is None:
            self._runtime_state_handler.reload()
            self._runtime_state_cache = next(
                iter(self._runtime_state_handler.data.values()), {}
            )
        return self._runtime_state_cache

    @property
    def exists(self) -> bool:
        """
        Check if runtime_state.json exists on disk.

        :return: True if file exists.
        """
        return self._runtime_state_handler.exists

    def _write_and_invalidate(self, state: dict) -> None:
        """
        Write state to disk and invalidate the in-memory cache.

        :param state: Full runtime state dict to persist.
        """
        self._runtime_state_handler.write_json(state)
        self._runtime_state_cache = None

    def reload_state(self) -> None:
        """Discard cached state so next access re-reads from disk."""
        self._runtime_state_cache = None

    def _resolve_default(self, cfg_key: str) -> str | None:
        """
        Resolve the default value for a config entry, falling back to the
        first available item if no default is explicitly set.

        :param cfg_key: Resolved config key.
        :return: Default value or None.
        """
        cfg = self.resolve_config(cfg_key)
        return cfg.get("default") or next(iter(cfg.get("items", [])), None)

    def _build_default_entry(self, mapping_key: str, item: str) -> dict:
        """
        Build the default entry for a single mapping_item.

        :param mapping_key: Mapping group key.
        :param item: Mapping_item identifier.
        :return: Dict of default fields and metadata.
        """
        placeholders = self.mappings[mapping_key]["placeholders"]
        config_fields = self.mappings[mapping_key].get("config_fields", {})
        metadata = self.mappings[mapping_key].get("metadata", {}).get(item, {})
        return {
            "runtime_id": str(uuid.uuid4()),
            "mapping_item": item,
            **{k: v for k, v in metadata.items() if isinstance(v, str)},
            **{
                field: self._resolve_default(
                    template.format(**{placeholders["key"]: item})
                )
                for field, template in config_fields.items()
                if field not in metadata
            },
        }

    def initialize_runtime_state(self) -> None:
        """
        Create runtime_state.json from defaults if absent, or add missing
        mapping entries to an existing file.
        """
        state = self.runtime_state if self.exists else {}
        missing = {
            mapping_key: [
                self._build_default_entry(mapping_key, item)
                for item in mapping.get("default_order") or mapping.get("items", [])
            ]
            for mapping_key, mapping in self.mappings.items()
            if mapping.get("mode") == "dynamic" and mapping_key not in state
        }
        if missing or not self.exists:
            merged = {**state, **missing}
            self._resolve_parent_refs(merged)
            self._write_and_invalidate(merged)

    def _resolve_parent_refs(self, state: dict) -> None:
        """
        Resolve string ``parent`` refs to runtime_ids; first match wins
        across mappings.

        :param state: Full runtime state dict, mutated in place.
        """
        item_to_id: dict = {}
        for entries in state.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                mi = entry.get("mapping_item")
                if mi and mi not in item_to_id:
                    item_to_id[mi] = entry["runtime_id"]
        for entries in state.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                parent = entry.get("parent")
                if parent and parent in item_to_id:
                    entry["parent"] = item_to_id[parent]

    def get_runtime_setting(
        self, mapping_key: str, index: int, setting_name: str
    ) -> object:
        """
        Retrieve a value from a runtime state entry.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param setting_name: Field to retrieve.
        :return: Stored value.
        """
        mapping_list = self.runtime_state.get(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range "
                f"for mapping '{mapping_key}'."
            )
        instance = mapping_list[index]
        if setting_name not in instance:
            raise KeyError(
                f"{self.__class__.__name__}: Runtime setting '{setting_name}' "
                f"not found in mapping '{mapping_key}' at index '{index}'."
            )
        return instance[setting_name]

    def format_metadata(self, mapping_key: str, index: int, template: str) -> str:
        """
        Substitute metadata placeholders in a template against a runtime entry.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param template: Template containing ``{placeholder}`` tokens.
        :return: Formatted string, or original on lookup failure.
        """
        if not isinstance(template, str) or "{" not in template:
            return template
        try:
            instance = self.runtime_state.get(mapping_key, [])[index]
            metadata_key = instance.get("mapping_item")
            metadata = (
                self.mappings.get(mapping_key, {})
                .get("metadata", {})
                .get(metadata_key, {})
            )
            key_placeholder = (
                self.mappings.get(mapping_key, {})
                .get("placeholders", {})
                .get("key", "")
            )
            extra = {key_placeholder: metadata_key} if key_placeholder else {}
            substitutions = {**instance, **metadata, **extra}
            return template.format(**substitutions)
        except Exception:
            return template

    def update_runtime_setting(
        self, mapping_key: str, index: int, setting_name: str, value: object
    ) -> None:
        """
        Update a single field in a runtime state entry.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param setting_name: Field to update.
        :param value: New value to set.
        """
        self.update_runtime_settings_batch(mapping_key, index, {setting_name: value})

    def update_runtime_settings_batch(
        self, mapping_key: str, index: int, updates: dict[str, object]
    ) -> None:
        """
        Update multiple fields on one runtime entry in a single write.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param updates: Field_name → value pairs to set.
        """
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range "
                f"for mapping '{mapping_key}'."
            )
        mapping_list[index].update(updates)
        self._write_and_invalidate(state)

    def insert_mapping_item(
        self,
        mapping_key: str,
        mapping_item: str,
        index: int | None = None,
        extra_fields: dict[str, object] | None = None,
    ) -> dict:
        """
        Insert a new mapping_item at the given position.

        :param mapping_key: Mapping group key.
        :param mapping_item: Mapping_item identifier to insert.
        :param index: Position to insert at, or None to append.
        :param extra_fields: Additional fields to set on the new entry.
        :return: Newly created entry dict.
        """
        state = self.runtime_state
        lst = state.setdefault(mapping_key, [])
        new_entry = self._build_default_entry(mapping_key, mapping_item)
        if extra_fields:
            new_entry.update(extra_fields)
        if index is None:
            lst.append(new_entry)
        else:
            lst.insert(index, new_entry)
        self._write_and_invalidate(state)
        return new_entry

    def delete_mapping_item(self, mapping_key: str, index: int) -> None:
        """
        Remove a mapping_item from the state list.

        :param mapping_key: Mapping group key.
        :param index: Position to remove.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst.pop(index)
        self._write_and_invalidate(state)

    def swap_mapping_items(self, mapping_key: str, a: int, b: int) -> None:
        """
        Swap two entries in the state list.

        :param mapping_key: Mapping group key.
        :param a: First index.
        :param b: Second index.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst[a], lst[b] = lst[b], lst[a]
        self._write_and_invalidate(state)

    def reset_runtime_state_for(self, mapping_key: str) -> None:
        """
        Reset the runtime state for a single mapping group, remapping
        surviving parent refs across child mappings.

        :param mapping_key: Group key to reset (e.g. 'widgets').
        """
        state = self.runtime_state
        mapping = self.mappings.get(mapping_key)
        if not mapping or mapping.get("mode") != "dynamic":
            return

        old_entries = state.get(mapping_key, [])
        old_ids = {e["runtime_id"]: e["mapping_item"] for e in old_entries}

        default_order = mapping.get("default_order") or mapping.get("items", [])
        state[mapping_key] = [
            self._build_default_entry(mapping_key, item) for item in default_order
        ]

        new_by_item = {e["mapping_item"]: e["runtime_id"] for e in state[mapping_key]}
        remap = {
            old_id: new_by_item[mi]
            for old_id, mi in old_ids.items()
            if mi in new_by_item
        }

        for key, entries in state.items():
            if key == mapping_key or not isinstance(entries, list):
                continue
            state[key] = [
                {**e, "parent": remap[e["parent"]]} if e.get("parent") in remap else e
                for e in entries
                if e.get("parent") not in old_ids or e.get("parent") in remap
            ]

        self._resolve_parent_refs(state)
        self._write_and_invalidate(state)

    def delete_orphans(self, parent_mapping: str, child_mapping: str) -> int:
        """
        Remove entries in ``child_mapping`` whose ``parent`` references a
        runtime_id that no longer exists anywhere in state. Children with no
        ``parent`` or with parents in other mappings are preserved.

        :param parent_mapping: Mapping key whose deletion triggered this call.
        :param child_mapping: Mapping key whose entries are inspected.
        :return: Number of entries removed.
        """
        state = self.runtime_state
        live_parent_ids = {
            entry["runtime_id"]
            for entries in state.values()
            if isinstance(entries, list)
            for entry in entries
        }
        children = state.get(child_mapping, [])
        cleaned = [
            c
            for c in children
            if c.get("parent") is None or c["parent"] in live_parent_ids
        ]
        removed = len(children) - len(cleaned)
        if removed:
            state[child_mapping] = cleaned
            self._write_and_invalidate(state)
        return removed
