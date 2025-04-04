# author: realcopacetic

from resources.lib.builders.builder_config import BUILDER_CONFIG, BUILDER_MAPPINGS
from resources.lib.shared.json import JSONMerger
from resources.lib.shared.utilities import SKINEXTRAS, Path, log, log_duration
from resources.lib.shared.xml import XMLMerger


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
        self.merged_json = self.json_merger.yield_merged_data()

        self.xml_merger = XMLMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=["xml"],
        )
        self.merged_xml = self.xml_merger.yield_merged_data()

    def combined_data(self):
        """
        Lazily combines JSON and XML data into one generator, yielding
        only the relevant content (JSON or XML) for each builder.

        :returns: Generator that yields combined data lazily, based on available data (JSON or XML).
        """
        yield from self.merged_json
        yield from self.merged_xml

    @log_duration
    def process(self, run_contexts=("startup",)):
        """
        Runs all eligible builders matching the given run contexts.

        :param run_contexts: A tuple or list of context strings to process.
        :returns: Dictionary of processed builder output if file write is not required.
        """
        values_to_write = {}
        values_to_return = {}

        for mapping_name, items_data in self.combined_data():
            mapping_values = self.all_mappings.get(mapping_name, {})
            loop_values = mapping_values.get("items")
            placeholders = mapping_values.get("placeholders", {})

            for builder, builder_elements in (items_data or {}).items():

                log(f"FUCK DEBUG {self.__class__.__name__} builder_elements {builder_elements}")
                builder_info = BUILDER_CONFIG.get(builder)
                if not builder_info or not builder_info["module"]:
                    continue

                if not any(
                    ctx in builder_info.get("run_contexts", []) for ctx in run_contexts
                ):
                    continue

                builder_class = builder_info["module"]
                builder_instance = builder_class(loop_values, placeholders)

                processed = {
                    k: v
                    for key, value in builder_elements.items()
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
