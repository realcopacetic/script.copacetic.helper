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
        self.mappings = mappings
        self.configs_handler = JSONHandler(configs_path)
        self.runtime_state_handler = JSONHandler(runtime_state_path)

    def initialize_runtime_state(self):
        """
        Initializes runtime_state.json based on user-defined schemas and defaults in configs.json.
        """
        configs_data = next(iter(self.configs_handler.data.values()), {})

        runtime_state = {
            mapping_key: [
                {
                    **{
                        k: v.format(**{mapping["placeholders"]["key"]: item})
                        for k, v in user_schema.get("strings", {}).items()
                    },
                    **{
                        k: configs_data.get(
                            v.format(**{mapping["placeholders"]["key"]: item}), {}
                        ).get("default")
                        for k, v in user_schema.get("configs", {}).items()
                    },
                    **{
                        k: configs_data.get(v, {}).get("default", "")
                        for k, v in user_schema.get("item_configs", {})
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
        runtime_data = next(iter(self.runtime_state_handler.data.values()), {})
        mapping_list = runtime_data.setdefault(mapping_key, [])

        if index >= len(mapping_list):
            raise IndexError(
                f"{self.__class__.__name__}: Index '{index}' out of range for mapping '{mapping_key}'."
            )

        mapping_list[index][setting_name] = value
        self.runtime_state_handler.write_json(runtime_data)

    def get_runtime_setting(self, mapping_key, index, setting_name):
        """
        Retrieves a specific runtime setting by index.

        :param mapping_key: The key identifying the mapping group.
        :param index: The index of the setting instance to retrieve.
        :param setting_name: The name of the setting to retrieve.
        :returns: The value of the requested runtime setting.
        """
        runtime_data = next(iter(self.runtime_state_handler.data.values()), {})
        mapping_list = runtime_data.get(mapping_key, [])

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
