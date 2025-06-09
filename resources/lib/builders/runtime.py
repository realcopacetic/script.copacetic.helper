# author: realcopacetic

from resources.lib.shared.json import JSONHandler


class RuntimeStateManager:
    """
    Manages initialization, retrieval, and updating of runtime settings stored in runtime_state.json.
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
        Load and return the current runtime state.

        :return: Dict of mapping_key → list of state entries.
        """
        self.runtime_state_handler.reload()
        return next(iter(self.runtime_state_handler.data.values()), {})

    @property
    def exists(self):
        """
        Check if runtime_state.json exists on disk.

        :return: True if file exists, False otherwise.
        """
        return self.runtime_state_handler.exists

    def _build_default_entry(self, mapping_key, item):
        """
        Build the default entry for a single mapping_item.

        :param mapping_key: The mapping group key.
        :param item: The mapping_item identifier.
        :return: Dict of default fields and metadata.
        """
        schema = self.mappings[mapping_key]["user_defined_schema"]
        placeholders = self.mappings[mapping_key]["placeholders"]
        return {
            "mapping_item": item,
            **{
                field: self.configs_data.get(
                    template.format(**{placeholders["key"]: item}), {}
                ).get("default")
                for field, template in schema.get("config_fields", {}).items()
            },
            **schema.get("metadata_fields", {}).get(item, {}),
        }

    def initialize_runtime_state(self):
        """
        Create runtime_state.json from defaults if not already present.

        :return: None
        """
        if self.exists:
            return

        runtime_state = {
            mapping_key: [
                self._build_default_entry(mapping_key, item)
                for item in mapping.get("default_order", [])
            ]
            for mapping_key, mapping in self.mappings.items()
            if "user_defined_schema" in mapping
        }

        self.runtime_state_handler.write_json(runtime_state)

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
        self.runtime_state_handler.write_json(state)

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
            item = self.get_runtime_setting(mapping_key, index, "mapping_item")
            meta = self.mappings[mapping_key].get("metadata", {}).get(item, {})
            return template.format(**meta)
        except Exception:
            return template

    def insert_mapping_item(self, mapping_key, index, item):
        """
        Insert a new mapping_item at the given position.

        :param mapping_key: The mapping group key.
        :param index: Position to insert at.
        :param item: The new mapping_item identifier.
        """
        state = self.runtime_state
        lst = state.setdefault(mapping_key, [])
        lst.insert(index, self._build_default_entry(mapping_key, item))
        self.runtime_state_handler.write_json(state)

    def delete_mapping_item(self, mapping_key, index):
        """
        Remove a mapping_item from the state list.

        :param mapping_key: The mapping group key.
        :param index: Position to remove.
        :return: None
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst.pop(index)
        self.runtime_state_handler.write_json(state)

    def swap_mapping_items(self, mapping_key, a, b):
        """
        Swap two entries in the state list.

        :param mapping_key: The mapping group key.
        :param i: First index.
        :param j: Second index.
        :return: None
        """
        state = self.runtime_state
        lst = state.get(mapping_key, [])
        lst[a], lst[b] = lst[b], lst[a]
        self.runtime_state_handler.write_json(state)
