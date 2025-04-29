# author: realcopacetic

from resources.lib.shared.json import JSONHandler


class RuntimeStateManager:

    def __init__(self, configs_path, runtime_state_path):
        self.configs_handler = JSONHandler(configs_path)
        self.runtime_state_handler = JSONHandler(runtime_state_path)

    def initialize_runtime_state(self):
        """Create runtime_state.json with default values from configs.json."""
        configs_data = next(iter(self.configs_handler.data.values()), {})
        runtime_defaults = {
            name: config.get("default")
            for name, config in configs_data.items()
            if config.get("storage") == "runtimejson"
        }
        runtime_state = {"runtime_settings": runtime_defaults}
        self.runtime_state_handler.write_json(runtime_state)

    def update_runtime_setting(self, setting_name, value):
        """Update a specific runtime setting."""
        runtime_data = next(iter(self.runtime_state_handler.data.values()), {})
        runtime_data.setdefault("runtime_settings", {})[setting_name] = value
        self.runtime_state_handler.write_json(runtime_data)

    def get_runtime_setting(self, setting_name):
        """Retrieve a specific runtime setting."""
        runtime_data = next(iter(self.runtime_state_handler.data.values()), {})
        settings = runtime_data.get("runtime_settings", {})

        if setting_name not in settings:
            raise KeyError(
                f"{self.__class__.__name__}: Runtime setting '{setting_name}' not found."
            )

        return settings[setting_name]
