# author: realcopacetic

from resources.lib.builders.builder_config import BUILDER_CONFIG, BUILDER_MAPPINGS
from resources.lib.shared.json import JSONMerger
from resources.lib.shared.utilities import SKINEXTRAS, Path, log, log_duration


class BuildElements:
    """
    Builds and writes processed data for skin elements like expressions and settings.
    Handles data merging across mappings and delegates processing to builder modules.
    """

    def __init__(self):
        """
        Initializes JSON mergers and loads all static and custom mappings.
        Sets up merged data and mapping configurations.
        """
        self.mapping_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=["custom_mappings"],
            grouping_key=None,
        )
        self.merged_mappings = dict(self.mapping_merger.cached_merged_data)
        self.all_mappings = {**BUILDER_MAPPINGS, **self.merged_mappings}

        self.json_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=list(BUILDER_CONFIG.keys()),
            grouping_key="mapping",
        )
        self.merged_data = self.json_merger.yield_merged_data()

    @log_duration
    def process(self, run_context="startup"):
        """
        Runs all eligible builders based on the given run context and writes output.

        :param run_context: Context in which builder runs (e.g., "startup", "runtime").
        :returns: Dictionary of processed builder output if file write is not required.
        """
        values_to_write = {}
        values_to_return = {}

        for mapping_name, items_data in self.merged_data:
            mapping_values = self.all_mappings.get(mapping_name, {})
            loop_values = mapping_values.get("items")
            placeholders = mapping_values.get("placeholders", {})

            for builder, json_elements in (items_data or {}).items():
                builder_info = BUILDER_CONFIG.get(builder)
                if not builder_info or not builder_info["module"]:
                    continue

                run_contexts = builder_info.get("run_contexts", [])
                if run_context not in run_contexts:
                    continue

                builder_class = builder_info["module"]
                dynamic_key = next(iter(builder_info.get("dynamic_key", {})), None)
                builder_instance = builder_class(loop_values, placeholders, dynamic_key)

                processed = {
                    k: v
                    for key, value in json_elements.items()
                    for d in builder_instance.process_elements(key, value)
                    for k, v in d.items()
                }

                output_target = (
                    values_to_write
                    if builder_info.get("file_type")
                    else values_to_return
                )

                output_target.setdefault(builder, {}).update(processed)

        for builder, builder_data in values_to_write.items():
            self.write_file(builder_data, builder)

        return values_to_return

    def write_file(self, processed_data, builder_name):
        """
        Writes the final processed data to disk using the correct handler.

        :param processed_data: Dictionary containing processed builder output.
        :param builder_name: Builder identifier used to look up file details.
        :returns: None
        """
        builder_info = BUILDER_CONFIG.get(builder_name, {})
        file_type = builder_info.get("file_type")
        file_path = builder_info.get("file_path")
        handler = builder_info.get("file_handler")
        write_kwargs = builder_info.get("write_kwargs", {})

        if not file_path:
            return

        if handler:
            handler = handler(file_path)

            write_method_name = f"write_{file_type}"
            write_method = getattr(handler, write_method_name, None)

            if write_method:
                write_method(processed_data, **write_kwargs)
                log(
                    f"{builder_name.capitalize()} saved to {file_type.upper()} file: {file_path}"
                )
