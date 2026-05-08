# author: realcopacetic
"""
Runtime state management for dynamic editor windows.

RuntimeStateManager owns the runtime_state.json read/write lifecycle and
holds references to ConfigsResolver and ControlsResolver. The resolvers
themselves live in resolver.py; loading lives in templates.py.
"""

import uuid

from resources.lib.builders.resolver import ConfigsResolver, ControlsResolver
from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONHandler


class RuntimeStateManager:
    """
    Manages runtime state in runtime_state.json plus configs and controls
    resolution. UUIDs provide stable, position-independent item identifiers.
    """

    def __init__(
        self,
        mappings: dict,
        configs_data: dict,
        controls_data: dict,
        runtime_state_path: str,
    ) -> None:
        """
        Initialise resolvers and runtime state handler.

        :param mappings: Dictionary containing all mappings.
        :param configs_data: {mapping_name: {tpl_name: tpl_data}}.
        :param controls_data: {mapping_name: {tpl_name: tpl_data}}.
        :param runtime_state_path: Path to runtime_state.json.
        """
        self._mappings = mappings
        self.configs = ConfigsResolver(mappings, configs_data)
        self.controls = ControlsResolver(mappings, controls_data)
        self._runtime_state_handler = JSONHandler(runtime_state_path)
        self._runtime_state_cache: dict | None = None

    @property
    def mappings(self) -> dict:
        """
        Retrieve merged mapping definitions.

        :return: Dict of mapping configurations.
        """
        return self._mappings

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

    def _build_default_entry(self, mapping_key: str, item: str) -> dict:
        """
        Build the default entry for a single mapping_item. ``parent`` is
        copied verbatim as a mapping_item string; ``_resolve_parent_refs``
        rewrites it to a runtime_id once full state is assembled.

        :param mapping_key: Mapping group key.
        :param item: Mapping_item identifier.
        :return: Dict of default fields and metadata.
        """
        placeholders = self.mappings[mapping_key]["placeholders"]
        seed_fields = self._seed_fields_for(mapping_key, item)
        metadata = self.mappings[mapping_key].get("metadata", {}).get(item, {})
        return {
            "runtime_id": str(uuid.uuid4()),
            "mapping_item": item,
            **{k: v for k, v in metadata.items() if isinstance(v, str)},
            **{
                field: self.configs.resolve_default(
                    template.format(**{placeholders["key"]: item})
                )
                for field, template in seed_fields.items()
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
                if not mi:
                    continue
                if mi in item_to_id:
                    log.debug(
                        f"{self.__class__.__name__}: duplicate mapping_item "
                        f"'{mi}' across mappings; first occurrence wins"
                    )
                    continue
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

    def mapping_item_for_runtime_id(self, runtime_id: str) -> str | None:
        """
        Reverse-lookup: find the mapping_item of the entry with this runtime_id.

        :param runtime_id: UUID to look up.
        :return: The entry's mapping_item, or None if not found.
        """
        for entries in self.runtime_state.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if entry.get("runtime_id") == runtime_id:
                    return entry.get("mapping_item")
        return None

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
        except (IndexError, KeyError) as e:
            log.debug(f"{self.__class__.__name__}: format_metadata fallback: {e}")
            return template

    def flatten_config_fields(self, mapping_key: str) -> dict[str, str]:
        """
        Flatten scoped config_fields into a single field→template map for
        registry lookups (control config_field_template resolution).

        :param mapping_key: Mapping group key.
        :return: Flat field→template map across all sections.
        """
        cfg = self.mappings.get(mapping_key, {}).get("config_fields", {})
        flat: dict[str, str] = {}
        for section in cfg.values():
            flat.update(section)
        return flat

    def _seed_fields_for(self, mapping_key: str, item: str) -> dict[str, str]:
        """
        Return the field→template map that applies to a given mapping_item.
        Combines the 'global' section with the item-specific section.

        :param mapping_key: Mapping group key.
        :param item: Mapping_item identifier.
        :return: Field→template map for fields that seed onto this entry.
        """
        cfg = self.mappings.get(mapping_key, {}).get("config_fields", {})
        return {**cfg.get("global", {}), **cfg.get(item, {})}

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
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range "
                f"for mapping '{mapping_key}'."
            )
        mapping_list[index][setting_name] = value
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

    def rebuild_mapping_item(
        self,
        mapping_key: str,
        mapping_item: str,
        index: int,
        preserve: dict[str, object],
    ) -> dict | None:
        """
        Replace the entry at ``index`` with a freshly-built entry for
        ``mapping_item``, carrying forward only the fields in ``preserve``
        (typically runtime_id and parent).

        :param mapping_key: Mapping group key.
        :param mapping_item: Preset name to seed from.
        :param index: Position in the state list.
        :param preserve: Fields to carry over from the existing entry.
        :return: The rebuilt entry, or None on failure.
        """
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            return None
        fresh = self._build_default_entry(mapping_key, mapping_item)
        fresh.update(preserve)
        mapping_list[index] = fresh
        self._write_and_invalidate(state)
        return fresh

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

    def delete_orphans(self, child_mapping: str) -> int:
        """
        Remove entries in ``child_mapping`` whose ``parent`` references a
        runtime_id that no longer exists anywhere in state. Children with no
        ``parent`` or with parents in other mappings are preserved.

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
