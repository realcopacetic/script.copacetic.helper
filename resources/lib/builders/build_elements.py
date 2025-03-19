# author: realcopacetic

import time

from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.default_mappings import DEFAULT_MAPPINGS
from resources.lib.shared.json import JSONMerger
from resources.lib.shared.utilities import SKINEXTRAS, Path, log


class BuildElements:
    """
    Handles merging and processing of expressions, skinsettings, and controls
    across multiple mappings.
    """

    def __init__(self):
        """
        Initializes the BuildElements class.
        """
        self.json_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=list(BUILDER_CONFIG.keys()),
        )
        self.merged_data = self.json_merger.get_merged_data()

    def process(self, run_context="startup"):
        """
        Iterates through each mapping lazily, applies loop values and placeholders,
        and processes all dynamically discovered items.

        :param process_controls: If True, includes building controls. If False, controls are skipped.
        :return: A tuple containing the accumulated expressions, skinsettings, and controls data.
        """

        processed_data = {}
        start_time = time.time()

        for mapping_name, items_data in self.json_merger.get_merged_data():
            mapping_defaults = DEFAULT_MAPPINGS.get("default_mappings", {}).get(
                mapping_name, {}
            )
            loop_values = mapping_defaults.get("items", {})
            placeholders = mapping_defaults.get("placeholders", {})

            for builder, elements in items_data.items():

                builder_info = BUILDER_CONFIG.get(builder)
                if not builder_info or not builder_info["module"]:
                    continue  # Skip if no valid builder is found

                if (
                    not builder_info.get("run_at_startup", True)
                    and run_context == "startup"
                ):
                    continue  # Skip builders flagged not to run at startup

                builder_instance = builder_info["module"](loop_values, placeholders)

                # Chain a generator to process each element lazily
                processed_data[builder] = {
                    k: v
                    for key, value in elements.items()
                    for d in builder_instance.process_elements(key, value)
                    for k, v in d.items()
                }

                log(
                    f"{self.__class__.__name__}: Rule processing took {time.time() - start_time:.4f} seconds",
                )
                self.write_file(processed_data[builder], builder)

    def write_file(self, processed_data, builder_name):
        """
        Handles writing processed data to the correct output format dynamically.

        :param processed_data: The processed data dictionary to be written
        :param builder_name: The builder name (e.g., "expressions", "skinsettings")
        """

        builder_info = BUILDER_CONFIG.get(builder_name, {})
        file_type = builder_info.get("file_type")
        file_path = builder_info.get("file_path")
        handler = builder_info.get("handler")
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
