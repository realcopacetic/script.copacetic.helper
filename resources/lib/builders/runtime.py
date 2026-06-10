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
from resources.lib.shared.utilities import infolabel

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
        self.controls = ControlsResolver(mappings, controls_data, self.configs)
        self._runtime_state_handler = JSONHandler(runtime_state_path)
        self._runtime_state_cache: dict | None = None
        self._resolved_cache: dict[tuple[str, int], dict] = {}
        self.state_version = 0

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
        self._resolved_cache.clear()
        self.state_version += 1

    def reload_state(self) -> None:
        """Discard cached state so next access re-reads from disk."""
        self._runtime_state_cache = None
        self._resolved_cache.clear()
        self.state_version += 1

    def _build_default_entry(self, mapping_key: str, item: str) -> dict:
        """
        Build the default entry for a single mapping_item: identity plus the
        structural ``parent`` ref only. All other metadata and config-field
        defaults resolve lazily at read time via ``resolved_entry``.

        :param mapping_key: Mapping group key.
        :param item: Mapping_item identifier.
        :return: Dict of identity fields (runtime_id, mapping_item, parent).
        """
        metadata = self.mappings[mapping_key].get("metadata", {}).get(item, {})
        return {
            "runtime_id": str(uuid.uuid4()),
            "mapping_item": item,
            **({"parent": metadata["parent"]} if "parent" in metadata else {}),
        }

    def resolved_entry(self, mapping_key: str, index: int) -> dict:
        """
        Return the entry at ``index`` with config-field defaults layered in
        for any field not explicitly set. Cached per (mapping, index) until
        the next state write or reload.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :return: Resolved entry dict; empty on lookup failure.
        """
        key = (mapping_key, index)
        if key in self._resolved_cache:
            return self._resolved_cache[key]
        try:
            entry = self.runtime_state[mapping_key][index]
        except (IndexError, KeyError):
            return {}
        resolved = self._fill_defaults(mapping_key, entry)
        self._resolved_cache[key] = resolved
        return resolved

    def _fill_defaults(self, mapping_key: str, entry: dict) -> dict:
        """
        Resolve a full entry: metadata base, stored entry over it, then
        config-field defaults filling any field still absent.

        :param mapping_key: Mapping group key.
        :param entry: Raw entry dict.
        :return: New dict; metadata + entry + resolved config defaults.
        """
        item = entry.get("mapping_item")
        if not item:
            return dict(entry)

        metadata = self.mappings[mapping_key].get("metadata", {}).get(item, {})
        metadata_strings = {k: v for k, v in metadata.items() if isinstance(v, str)}
        base = {**metadata_strings, **entry}

        seed_fields = self._seed_fields_for(mapping_key, item)
        pending = {f: t for f, t in seed_fields.items() if f not in base}
        if not pending:
            return base

        placeholders = self.mappings[mapping_key].get("placeholders", {})
        base_subs = {placeholders.get("key", ""): item}
        base_subs.update({k: v for k, v in base.items() if isinstance(v, str)})
        resolved = {}

        while pending:
            progressed = False
            for field, template in list(pending.items()):
                sub = {**base_subs, **resolved}
                try:
                    template.format(**sub)
                except KeyError:
                    continue
                resolved[field] = self.configs.resolve_default(
                    mapping_key, template, sub
                )
                del pending[field]
                progressed = True
            if not progressed:
                raise ValueError(
                    f"Unresolvable seed templates in {mapping_key}/{item}: "
                    f"{list(pending)}"
                )
        return {**base, **resolved}

    def initialize_runtime_state(self) -> None:
        """
        Create runtime_state.json from defaults if absent, or add missing
        mapping entries to an existing file.
        """
        state = self.runtime_state if self.exists else {}
        missing = {
            mapping_key: [
                self._build_default_entry(mapping_key, item)
                for item in (
                    mapping["default_order"]
                    if "default_order" in mapping
                    else mapping.get("items", [])
                )
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

    def entry_substitutions(
        self,
        mapping_key: str,
        index: int,
        *,
        include_metadata: bool = False,
    ) -> dict:
        """
        Build the substitution dict for a runtime entry: resolved string
        fields, mapping key placeholder, and optionally metadata layered
        beneath.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param include_metadata: Layer mapping metadata under entry fields.
        :return: Substitution dict; empty on lookup failure.
        """
        resolved = self.resolved_entry(mapping_key, index)
        if not resolved:
            return {}

        mapping = self.mappings.get(mapping_key, {})
        item = resolved["mapping_item"]
        base = (
            dict(mapping.get("metadata", {}).get(item, {})) if include_metadata else {}
        )
        base.update({k: v for k, v in resolved.items() if isinstance(v, str)})
        key_placeholder = mapping.get("placeholders", {}).get("key", "")
        if key_placeholder:
            base[key_placeholder] = item
        base["mapping"] = mapping_key
        base["index"] = index
        return base

    def format_metadata(
        self,
        mapping_key: str,
        index: int,
        template: str,
        *,
        localize: bool = False,
    ) -> str:
        """
        Substitute placeholders in a template against a runtime entry,
        optionally resolving Kodi ``$`` tokens via infolabel.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param template: Template containing ``{placeholder}`` tokens.
        :param localize: If True, resolve ``$``-prefixed tokens via infolabel.
        :return: Formatted string, or original on lookup failure.
        """

        if not isinstance(template, str) or "{" not in template:
            formatted = template
        else:
            try:
                formatted = template.format(
                    **self.entry_substitutions(
                        mapping_key, index, include_metadata=True
                    )
                )
            except KeyError as e:
                log.debug(f"{self.__class__.__name__}: format_metadata fallback: {e}")
                formatted = template

        return (
            infolabel(formatted)
            if localize and isinstance(formatted, str) and formatted.startswith("$")
            else formatted
        )

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
        self.update_runtime_settings(mapping_key, index, {setting_name: value})

    def update_runtime_settings(
        self, mapping_key: str, index: int, fields: dict[str, object]
    ) -> None:
        """
        Update multiple fields in a runtime state entry with a single write.

        :param mapping_key: Mapping group key.
        :param index: Position in the state list.
        :param fields: Field → value pairs to set.
        """
        self.reload_state()
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range "
                f"for mapping '{mapping_key}'."
            )
        mapping_list[index].update(fields)
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
        self._resolve_parent_refs(state)
        self._write_and_invalidate(state)
        return new_entry

    def insert_position_for(
        self, mapping_key: str, parent_filter: str | None, after_index: int | None
    ) -> int:
        """
        Source index for a new entry: after ``after_index`` when given;
        else after the last sibling of ``parent_filter``, before the first
        child of any later parent, or appended at the end.

        :param mapping_key: Mapping group key.
        :param parent_filter: Parent runtime_id scoping the insert, if any.
        :param after_index: Source index of the entry to insert after.
        :return: Source index to pass to insert_mapping_item.
        """
        if after_index is not None:
            return after_index + 1
        flat = self.runtime_state.get(mapping_key, [])
        if not parent_filter:
            return len(flat)
        last_sibling = next(
            (
                i
                for i in range(len(flat) - 1, -1, -1)
                if flat[i].get("parent") == parent_filter
            ),
            None,
        )
        if last_sibling is not None:
            return last_sibling + 1
        later_ids = self._later_parent_ids(mapping_key, parent_filter)
        return next(
            (i for i, e in enumerate(flat) if e.get("parent") in later_ids),
            len(flat),
        )

    def _later_parent_ids(self, child_mapping: str, parent_filter: str) -> set[str]:
        """
        Runtime_ids of parent entries ordered after ``parent_filter`` in
        the parent mapping.

        :param child_mapping: The child mapping key (used to skip self).
        :param parent_filter: Parent runtime_id to anchor on.
        :return: Set of runtime_ids for later parents, or empty set.
        """
        for key, entries in self.runtime_state.items():
            if key == child_mapping or not isinstance(entries, list):
                continue
            for i, entry in enumerate(entries):
                if entry.get("runtime_id") == parent_filter:
                    return {e["runtime_id"] for e in entries[i + 1 :]}
        return set()

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
        self.reload_state()
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])
        if not 0 <= index < len(mapping_list):
            return None
        fresh = self._build_default_entry(mapping_key, mapping_item)
        fresh.update(preserve)
        mapping_list[index] = fresh
        self._resolve_parent_refs(state)
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
