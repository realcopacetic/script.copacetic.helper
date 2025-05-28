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
        """return: All mapping definitions (BUILDER_MAPPINGS + custom_mappings)."""
        return self._mappings

    @property
    def configs_data(self):
        """return: Flat dict of all configs.json entries, keyed by setting_id."""
        return next(iter(self.configs_handler.data.values()), {})

    @property
    def runtime_state(self):
        """return: Flat dict of current runtime JSON data."""
        self.runtime_state_handler.reload()
        return next(iter(self.runtime_state_handler.data.values()), {})

    def exists(self):
        """
        Returns True if the runtime_state.json already exists on disk.
        """
        return self.runtime_state_handler.exists()

    def initialize_runtime_state(self):
        """
        Initializes runtime_state.json at build time based on user-defined schemas
        in custom mapping files and defaults in configs.json.
        """
        if self.exists:
            return

        runtime_state = {
            mapping_key: [
                {
                    "mapping_item": item,
                    **{
                        field_name: self.configs_data.get(
                            template.format(**{mapping["placeholders"]["key"]: item}),
                            {},
                        ).get("default")
                        for field_name, template in user_schema.get(
                            "config_fields", {}
                        ).items()
                    },
                    **{
                        meta_key: default
                        for meta_key, default in user_schema.get("metadata_fields", {})
                        .get(item, {})
                        .items()
                    },
                }
                for item in mapping.get("default_order", [])
            ]
            for mapping_key, mapping in self.mappings.items()
            if (user_schema := mapping.get("user_defined_schema"))
        }

        self.runtime_state_handler.write_json(runtime_state)

    def update_runtime_setting(self, mapping_key, index, setting_name, value):
        """
        Updates a specific runtime setting within runtime_state.json.

        :param mapping_key: The key identifying the mapping group.
        :param index: The index of the setting instance to update.
        :param setting_name: The name of the setting to update.
        :param value: The new value for the setting.
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
        Retrieves a specific runtime setting by index.

        :param mapping_key: The key identifying the mapping group.
        :param index: The index of the setting instance to retrieve.
        :param setting_name: The name of the setting to retrieve.
        :returns: The value of the requested runtime setting.
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
        If template contains “{…}”, look up the runtime_state[mapping_key][index].mapping_item
        and then its metadata dict, and format the template. Otherwise return template.
        """
        if not isinstance(template, str) or "{" not in template:
            return template
        try:
            item = self.get_runtime_setting(mapping_key, index, "mapping_item")
            meta = self.mappings[mapping_key].get("metadata", {}).get(item, {})
            return template.format(**meta)
        except Exception:
            return template
