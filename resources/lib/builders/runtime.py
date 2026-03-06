# author: realcopacetic

import uuid

from resources.lib.shared.json import JSONHandler


class RuntimeStateManager:
    """
    Manages initialization, retrieval, and updating of runtime settings stored in runtime_state.json.
    Uses UUIDs for stable, position-independent item identifiers.
    """

    def __init__(self, mappings, configs_path, runtime_state_path):
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
    def mappings(self):
        """
        Retrieve merged mapping definitions.

        return: Dict of mapping configurations.
        """
        return self._mappings

    @property
    def configs_data(self):
        """
        Get flattened configs.json entries.

        return: Dict of setting_id → config data.
        """
        return next(iter(self.configs_handler.data.values()), {})

    @property
    def runtime_state(self):
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

    def _write_and_invalidate(self, state):
        """
        Write state to disk and invalidate the in-memory cache.

        :param state: The full runtime state dict to persist.
        """
        self.runtime_state_handler.write_json(state)
        self._runtime_state_cache = None

    @property
    def exists(self):
        """
        Check if runtime_state.json exists on disk.

        :return: True if file exists, False otherwise.
        """
        return self.runtime_state_handler.exists

    def _resolve_default(self, cfg_key: str) -> str | None:
        """
        Resolve the default value for a config entry.
        Falls back to the first available item if no default is explicitly set.

        :param cfg_key: The resolved config key to look up in configs_data.
        :return: The default value, or None if no items are defined.
        """
        cfg = self.configs_data.get(cfg_key, {})
        return cfg.get("default") or next(iter(cfg.get("items", [])), None)

    def _build_default_entry(self, mapping_key, item):
        """
        Build the default entry for a single mapping_item.

        :param mapping_key: The mapping group key.
        :param item: The mapping_item identifier.
        :return: Dict of default fields and metadata.
        """
        placeholders = self.mappings[mapping_key]["placeholders"]
        config_fields = self.mappings[mapping_key].get("config_fields", {})
        return {
            "runtime_id": str(uuid.uuid4()),
            "mapping_item": item,
            **{
                field: self._resolve_default(
                    template.format(**{placeholders["key"]: item})
                )
                for field, template in config_fields.items()
            },
        }

    def initialize_runtime_state(self):
        """
        Create runtime_state.json from defaults if not already present.
        """
        if self.exists:
            return

        runtime_state = {
            mapping_key: [
                self._build_default_entry(mapping_key, item)
                for item in mapping.get("default_order", [])
            ]
            for mapping_key, mapping in self.mappings.items()
            if "config_fields" in mapping
        }

        self._write_and_invalidate(runtime_state)

    def reset_runtime_state_for(self, mapping_key):
        """
        Reset the runtime state for a single mapping group.

        :param mapping_key: The group key to reset (e.g. 'widgets').
        """
        state = self.runtime_state
        mapping = self.mappings.get(mapping_key)
        if not mapping or "config_fields" not in mapping:
            return

        default_order = mapping.get("default_order", [])
        state[mapping_key] = [
            self._build_default_entry(mapping_key, item) for item in default_order
        ]
        self._write_and_invalidate(state)

    def update_runtime_setting(self, mapping_key, index, setting_name, value):
        """
        Update a field in a runtime state entry.

        :param mapping_key: The mapping group key.
        :param index: Position in the state list.
        :param setting_name: Field to update.
        :param value: New value to set.
        """
        state = self.runtime_state
        mapping_list = state.setdefault(mapping_key, [])

        if index >= len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range for mapping '{mapping_key}'."
            )

        mapping_list[index][setting_name] = value
        self._write_and_invalidate(state)

    def get_runtime_setting(self, mapping_key, index, setting_name):
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

    def format_metadata(self, mapping_key, index, template):
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

    def insert_mapping_item(self, mapping_key, mapping_item, index=None):
        """
        Insert a new mapping_item at the given position.

        :param mapping_key: The mapping group key.
        :param index: Position to insert at.
        :param item: The new mapping_item identifier.
        """
        state = self.runtime_state
        lst = state.setdefault(mapping_key, [])
        new_entry = self._build_default_entry(mapping_key, mapping_item)

        if index is None:
            lst.append(new_entry)
        else:
            lst.insert(index, new_entry)

        self._write_and_invalidate(state)
        return new_entry

    def delete_mapping_item(self, mapping_key, index):
        """
        Remove a mapping_item from the state list.

        :param mapping_key: The mapping group key.
        :param index: Position to remove.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst.pop(index)
        self._write_and_invalidate(state)

    def swap_mapping_items(self, mapping_key, a, b):
        """
        Swap two entries in the state list.

        :param mapping_key: The mapping group key.
        :param i: First index.
        :param j: Second index.
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst[a], lst[b] = lst[b], lst[a]
        self._write_and_invalidate(state)
