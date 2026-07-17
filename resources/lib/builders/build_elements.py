# author: realcopacetic

from pathlib import Path

from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.runtime import RuntimeStateManager
from resources.lib.builders.templates import (
    load_template_data_from_source,
    write_template_cache,
)
from resources.lib.shared import logger as log
from resources.lib.shared.json import JSONMerger
from resources.lib.shared.utilities import (
    TEMPLATES,
    RUNTIME_STATE,
)
from resources.lib.shared.xml import XMLDictConverter, XMLMerger


class BuildElements:
    """
    Builds and writes processed data for skin elements like expressions and settings.
    Handles data merging across mappings and delegates processing to builder modules.
    """

    def __init__(self, builders_to_run=None):
        """
        Load templates and prepare the runtime manager.

        :param builders_to_run: Subset of builders to run; default is all.
        """
        self.selected = (
            list(BUILDER_CONFIG.keys()) if builders_to_run is None else builders_to_run
        )
        (
            self.all_mappings,
            self.configs_data,
            self.controls_data,
        ) = load_template_data_from_source(TEMPLATES)

        self.runtime_manager = RuntimeStateManager(
            mappings=self.all_mappings,
            configs_data=self.configs_data,
            controls_data=self.controls_data,
            runtime_state_path=RUNTIME_STATE,
        )

    def _merged_inputs(self):
        """
        Yield (mapping_name, items_data) pairs across JSON and XML inputs
        for the selected builders.
        """
        json_merger = JSONMerger(
            base_folder=Path(TEMPLATES),
            subfolders=self.selected,
            grouping_key="mapping",
        )
        yield from json_merger.yield_merged_data()

        if "includes" not in self.selected:
            return

        read_kwargs = BUILDER_CONFIG["includes"]["read_kwargs"]
        xml_merger = XMLMerger(
            base_folder=Path(TEMPLATES),
            subfolders=["includes"],
            **read_kwargs,
        )
        for mapping_name, xml_root in xml_merger.yield_merged_data():
            yield mapping_name, XMLDictConverter(xml_root, **read_kwargs).xml_to_dict()

    def _process_builders(self):
        """
        Run each selected builder against its inputs.

        :return: Dict of {builder_name: {key: value}}.
        """
        values_to_write = {}
        for mapping_name, items_data in self._merged_inputs():
            mapping_values = self.all_mappings.get(mapping_name, {})
            for builder, builder_elements in (items_data or {}).items():
                builder_info = BUILDER_CONFIG.get(builder)
                if not builder_info or not builder_info["module"]:
                    continue
                builder_instance = builder_info["module"](
                    mapping_name, mapping_values, self.runtime_manager
                )
                processed = {
                    k: v
                    for key, value in builder_elements.items()
                    for d in builder_instance.process_elements(key, value)
                    for k, v in d.items()
                }
                values_to_write.setdefault(builder, {}).update(processed)
        return values_to_write

    @log.duration
    def run(self):
        """
        Execute the build pipeline. Runs the selected builders, writes
        outputs, and refreshes the template cache. Seeds any runtime state
        mappings missing from disk before builders run.
        """
        self.runtime_manager.initialize_runtime_state()
        values_to_write = self._process_builders()

        for builder, builder_data in values_to_write.items():
            log.debug(
                f"{self.__class__.__name__}: {builder} → "
                f"{len(builder_data)} entries generated"
            )
            self._write_file(builder_data, builder)

        write_template_cache(self.all_mappings, self.configs_data, self.controls_data)

    def _write_file(self, processed_data, builder_name):
        """
        Write builder output to disk using the handler in BUILDER_CONFIG.

        :param processed_data: Dictionary containing processed builder output.
        :param builder_name: Builder identifier used to look up file details.
        """
        builder_info = BUILDER_CONFIG.get(builder_name, {})
        write_path = builder_info.get("write_path")
        write_handler = builder_info.get("write_handler")
        write_kwargs = builder_info.get("write_kwargs", {})

        if not write_path or not write_handler:
            return

        handler = write_handler(write_path)
        handler.write_xml(processed_data, **write_kwargs)
        log.info(f"{builder_name.capitalize()} saved to XML file: {write_path}")
