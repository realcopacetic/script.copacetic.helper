# author: realcopacetic

from pathlib import Path

from resources.lib.builders.builder_config import BUILDER_CONFIG, BUILDER_MAPPINGS
from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.shared.json import JSONHandler, JSONMerger
from resources.lib.shared.utilities import (
    CONFIGS,
    RUNTIME_STATE,
    SKINEXTRAS,
    condition,
    log,
    log_duration,
    skin_string,
)
from resources.lib.shared.xml import XMLDictConverter, XMLMerger


class BuildElements:
    """
    Builds and writes processed data for skin elements like expressions and settings.
    Handles data merging across mappings and delegates processing to builder modules.
    """

    def __init__(self, run_context="prep", builders_to_run=None, force_rebuild=False):
        """
        Initializes JSON mergers and loads all static and custom mappings.
        Sets up merged data and mapping configurations.

        :param run_context: Runtime context string ("prep", "build", "boot", or "runtime").
        :param builders_to_run: List of builders requiring processing.
        :param force_rebuild: Ensures all builders with given run_context are processed.
        """
        self.run_context = run_context
        self.runtime_manager = None
        self.force_rebuild = force_rebuild
        self.builders_to_run = (
            self._default_builders()
            if (force_rebuild or builders_to_run is None)
            else builders_to_run
        )

        self.mapping_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=["custom_mappings"],
            grouping_key=None,
        )
        self.all_mappings = {
            **BUILDER_MAPPINGS,
            **dict(self.mapping_merger.cached_merged_data),
        }

        self.json_merger = JSONMerger(
            base_folder=Path(SKINEXTRAS) / "builders",
            subfolders=self.builders_to_run,
            grouping_key="mapping",
        )
        self.merged_json = self.json_merger.yield_merged_data()

        if "includes" in self.builders_to_run:
            self.read_kwargs = BUILDER_CONFIG["includes"]["read_kwargs"]
            self.xml_merger = XMLMerger(
                base_folder=Path(SKINEXTRAS) / "builders",
                subfolders=["includes"],
                **self.read_kwargs,
            )
            self.merged_xml = self.xml_merger.yield_merged_data()
        else:
            self.merged_xml = None
            self.read_kwargs = {}

        self.process()

    def _default_builders(self):
        return [
            builder
            for builder, config in BUILDER_CONFIG.items()
            if self.run_context in config.get("run_contexts", [])
        ]

    def combined_data(self):
        """
        Lazily combines JSON and XML data into one generator, yielding
        only the relevant content (JSON or XML) for each builder.

        :returns: Generator that yields combined data lazily, based on available data (JSON or XML).
        """
        yield from self.merged_json
        if self.merged_xml:
            yield from (
                (
                    mapping_name,
                    XMLDictConverter(xml_root, **self.read_kwargs).xml_to_dict(),
                )
                for mapping_name, xml_root in self.merged_xml
            )

    @log_duration
    def process(self):
        """
        Runs all eligible builders matching the given run context.

        :returns: Dictionary of processed builder output if file write is not required.
        """
        values_to_write = {}
        values_to_return = {}

        # Initialize runtime states and skin strings after builders finish processing configs.json
        if self.run_context == "build":
            self.runtime_manager = RuntimeStateManager(
                mappings=self.all_mappings,
                configs_path=CONFIGS,
                runtime_state_path=RUNTIME_STATE,
            )
            self.initialize_runtime_states()
            self.initialize_skinstrings()

        for mapping_name, items_data in self.combined_data():
            mapping_values = self.all_mappings.get(mapping_name, {})

            for builder, builder_elements in (items_data or {}).items():
                builder_info = BUILDER_CONFIG.get(builder)
                if not builder_info or not builder_info["module"]:
                    continue

                if self.run_context not in builder_info.get("run_contexts", []):
                    continue

                builder_class = builder_info["module"]
                builder_instance = builder_class(
                    mapping_name, mapping_values, self.runtime_manager
                )

                processed = {
                    k: v
                    for key, value in builder_elements.items()
                    for d in builder_instance.process_elements(key, value)
                    for k, v in d.items()
                }

                output_target = (
                    values_to_write
                    if builder_info.get("write_type")
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

        write_type = builder_info.get("write_type")
        write_path = builder_info.get("write_path")
        write_handler = builder_info.get("write_handler")
        write_kwargs = builder_info.get("write_kwargs", {})

        if not write_path:
            return

        if write_handler:
            handler = write_handler(write_path)
            method_name = f"write_{write_type}"
            method = getattr(handler, method_name, None)

            if method:
                method(processed_data, **write_kwargs)
                log(
                    f"{builder_name.capitalize()} saved to {write_type.upper()} file: {write_path}"
                )

    def initialize_runtime_states(self):
        """
        Initializes runtime_state.json based on default values in configs.json.
        This ensures default runtime states are set at build time.
        """
        self.runtime_manager.initialize_runtime_state()

    def initialize_skinstrings(self):
        """
        Initializes skin string defaults based on configs.json.
        This ensures default skin strings are set at build time.
        """
        json_handler = JSONHandler(CONFIGS)
        configs_data = next(iter(json_handler.data.values()), {})

        if not configs_data:
            log(
                f"{self.__class__.__name__}: Configs file missing or empty at {CONFIGS}",
                force=True,
            )
            return

        for setting_key, setting_data in configs_data.items():
            default_value = setting_data.get("default")
            storage_type = setting_data.get("storage", "skinstring")

            if storage_type != "skinstring" or default_value is None:
                continue

            if not condition(f"Skin.String({setting_key})"):
                skin_string(setting_key, default_value)
                log(
                    f"{self.__class__.__name__}: Default skinstring '{setting_key}' initialized to '{default_value}'."
                )
