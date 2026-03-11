# author: realcopacetic

import uuid

from resources.lib.shared.json import JSONHandler


class RuntimeStateManager:
    """
    Manages initialization, retrieval, and updating of runtime settings stored in runtime_state.json.
    Uses UUIDs for stable, position-independent item identifiers.
    """

    def __init__(
        self, mappings: dict, configs_path: str, runtime_state_path: str
    ) -> None:
        """
        Initializes RuntimeStateManager with provided JSON paths and mappings.

        :param mappings: Dictionary containing all mappings with potential user schemas.
        :param configs_path: Path to configs.json for fetching default configuration values.
        :param runtime_state_path: Path to runtime_state.json for persisting runtime states.
        """
        self._mappings = mappings
        self.configs_handler = JSONHandler(configs_path)
        self.runtime_state_handler = JSONHandler(runtime_state_path)
        self._runtime_state_cache = None

    @property
    def mappings(self) -> dict:
        """
        Retrieve merged mapping definitions.

        :return: Dict of mapping configurations.
        """
        return self._mappings

    @property
    def configs_data(self) -> dict:
        """
        Get flattened configs.json entries.

        :return: Dict of setting_id → config data.
        """
        return next(iter(self.configs_handler.data.values()), {})

    @property
    def runtime_state(self) -> dict:
        """
        Load and return the current runtime state. Uses an in-memory cache
        to avoid redundant disk reads; cache is invalidated after writes.

        :return: Dict of mapping_key → list of state entries.
        """
        if self._runtime_state_cache is None:
            self.runtime_state_handler.reload()
            self._runtime_state_cache = next(
                iter(self.runtime_state_handler.data.values()), {}
            )
        return self._runtime_state_cache

    @property
    def exists(self) -> bool:
        """
        Check if runtime_state.json exists on disk.

        :return: True if file exists, False otherwise.
        """
        return self.runtime_state_handler.exists

    def _write_and_invalidate(self, state: dict) -> None:
        """
        Write state to disk and invalidate the in-memory cache.

        :param state: The full runtime state dict to persist.
        """
        self.runtime_state_handler.write_json(state)
        self._runtime_state_cache = None

    def reload_state(self) -> None:
        """Discard cached state so next access re-reads from disk."""
        self._runtime_state_cache = None

    def _resolve_default(self, cfg_key: str) -> str | None:
        """
        Resolve the default value for a config entry.
        Falls back to the first available item if no default is explicitly set.

        :param cfg_key: The resolved config key to look up in configs_data.
        :return: The default value, or None if no items are defined.
        """
        cfg = self.configs_data.get(cfg_key, {})
        return cfg.get("default") or next(iter(cfg.get("items", [])), None)

    def _build_default_entry(self, mapping_key: str, item: str) -> dict:
        """
        Build the default entry for a single mapping_item.

        :param mapping_key: The mapping group key.
        :param item: The mapping_item identifier.
        :return: Dict of default fields and metadata.
        """
        placeholders = self.mappings[mapping_key]["placeholders"]
        config_fields = self.mappings[mapping_key].get("config_fields", {})
        metadata = self.mappings[mapping_key].get("metadata", {}).get(item, {})
        return {
            "runtime_id": str(uuid.uuid4()),
            "mapping_item": item,
            **metadata,
            **{
                field: self._resolve_default(
                    template.format(**{placeholders["key"]: item})
                )
                for field, template in config_fields.items()
            },
        }

    def initialize_runtime_state(self) -> None:
        """
        Create runtime_state.json from defaults if not present,
        or add missing mapping entries to an existing file.
        """
        state = self.runtime_state if self.exists else {}
        missing = {
            mapping_key: [
                self._build_default_entry(mapping_key, item)
                for item in mapping.get("default_order", [])
            ]
            for mapping_key, mapping in self.mappings.items()
            if "config_fields" in mapping and mapping_key not in state
        }
        if missing or not self.exists:
            merged = {**state, **missing}
            self._resolve_parent_refs(merged)
            self._write_and_invalidate(merged)

    def _resolve_parent_refs(self, state: dict) -> None:
        """
        Replace mapping_item parent references with runtime_ids.
        For each entry with a ``parent`` field whose value matches a
        ``mapping_item`` string, substitute the corresponding ``runtime_id``.
        If multiple mappings share a ``mapping_item`` name, the first
        encountered match wins. This is safe as long as parent references
        always target a different mapping group than their own.

        :param state: Full runtime state dict, mutated in place.
        """
        # Build global lookup: mapping_item → runtime_id (first match wins)
        item_to_id = {}
        for entries in state.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                mi = entry.get("mapping_item")
                if mi and mi not in item_to_id:
                    item_to_id[mi] = entry["runtime_id"]

        # Resolve parent refs
        for entries in state.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                parent = entry.get("parent")
                if parent and parent in item_to_id:
                    entry["parent"] = item_to_id[parent]

    def get_runtime_setting(
        self, mapping_key: str, index: int, setting_name: str
    ) -> str:
        """
        Retrieve a value from a runtime state entry.

        :param mapping_key: The mapping group key.
        :param index: Position in the state list.
        :param setting_name: Field to retrieve.
        :return: The stored value.
        """
        mapping_list = self.runtime_state.get(mapping_key, [])

        if index >= len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range for mapping '{mapping_key}'."
            )

        instance = mapping_list[index]
        if setting_name not in instance:
            raise KeyError(
                f"{self.__class__.__name__}: Runtime setting '{setting_name}' not found in mapping '{mapping_key}' at index '{index}'."
            )

        return instance[setting_name]

    def format_metadata(self, mapping_key: str, index: int, template: str) -> str:
        """
        Substitute metadata placeholders in a template string.

        :param mapping_key: The mapping group key.
        :param index: Position in the state list.
        :param template: Template with placeholders.
        :return: Formatted string or original template.
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
        self, mapping_key: str, index: int, setting_name: str, value: str
    ) -> None:
        """
        Update a field in a runtime state entry.

        :param mapping_key: The mapping group key.
        :param index: Position in the state list.
        :param setting_name: Field to update.
        :param value: New value to set.
        """
        self.update_runtime_settings_batch(mapping_key, index, {setting_name: value})

    def update_runtime_settings_batch(
        self, mapping_key: str, index: int, updates: dict[str, str]
    ) -> None:
        """
        Update multiple fields on a single runtime state entry in one write.

        :param mapping_key: The mapping group key.
        :param index: Position in the state list.
        :param updates: Dict of field_name → value pairs to set.
        """
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])

        if index >= len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range "
                f"for mapping '{mapping_key}'."
            )

        mapping_list[index].update(updates)
        self._write_and_invalidate(state)

    def insert_mapping_item(
        self, mapping_key: str, mapping_item: str, index: int | None = None,
        extra_fields: dict[str, str] | None = None,
    ) -> dict:
        """
        Insert a new mapping_item at the given position.

        :param mapping_key: The mapping group key.
        :param mapping_item: The mapping_item identifier to insert.
        :param index: Position to insert at, or None to append.
        :param extra_fields: Additional fields to set on the new entry before writing.
        :return: The newly created entry dict.
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

        :param mapping_key: The mapping group key.
        :param index: Position to remove.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst.pop(index)
        self._write_and_invalidate(state)

    def swap_mapping_items(self, mapping_key: str, a: int, b: int) -> None:
        """
        Swap two entries in the state list.

        :param mapping_key: The mapping group key.
        :param a: First index.
        :param b: Second index.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst[a], lst[b] = lst[b], lst[a]
        self._write_and_invalidate(state)

    def reset_runtime_state_for(self, mapping_key: str) -> None:
        """
        Reset the runtime state for a single mapping group.

        :param mapping_key: The group key to reset (e.g. 'widgets').
        """
        state = self.runtime_state
        mapping = self.mappings.get(mapping_key)
        if not mapping or "config_fields" not in mapping:
            return

        old_entries = state.get(mapping_key, [])
        old_ids = {e["runtime_id"]: e["mapping_item"] for e in old_entries}

        default_order = mapping.get("default_order", [])
        state[mapping_key] = [
            self._build_default_entry(mapping_key, item) for item in default_order
        ]
        new_ids = {e["runtime_id"] for e in state[mapping_key]}

        # Remap surviving parents (old→new via matching mapping_item)
        new_by_item = {e["mapping_item"]: e["runtime_id"] for e in state[mapping_key]}
        remap = {
            old_id: new_by_item[mi]
            for old_id, mi in old_ids.items()
            if mi in new_by_item
        }

        # Reparent or delete children across all other mappings
        for key, entries in state.items():
            if key == mapping_key or not isinstance(entries, list):
                continue
            state[key] = [
                {**e, "parent": remap[e["parent"]]}
                if e.get("parent") in remap
                else e
                for e in entries
                if e.get("parent") not in old_ids or e.get("parent") in remap
            ]

        self._resolve_parent_refs(state)
        self._write_and_invalidate(state)

    def delete_orphans(self, parent_mapping: str, child_mapping: str) -> int:
        """
        Remove entries in child_mapping whose parent field doesn't
        match any runtime_id in parent_mapping.

        :param parent_mapping: The mapping key for parent entries.
        :param child_mapping: The mapping key for child entries.
        :return: Number of entries removed.
        """
        state = self.runtime_state
        parent_ids = {
            entry["runtime_id"] for entry in state.get(parent_mapping, [])
        }
        children = state.get(child_mapping, [])
        cleaned = [c for c in children if c.get("parent") in parent_ids]
        removed = len(children) - len(cleaned)
        if removed:
            state[child_mapping] = cleaned
            self._write_and_invalidate(state)
        return removed
