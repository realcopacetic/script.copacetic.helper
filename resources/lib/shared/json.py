# author: realcopacetic

import json

from resources.lib.shared.utilities import log, Path


class JSONHandler:
    """
    Handles loading, parsing, validating, and writing JSON files.
    Supports multiple files per folder and allows dynamic folder selection.
    """

    def __init__(self, path):
        """Initializes the JSON handler with a file or folder path."""
        self.path = Path(path)
        self.data = self._load_json()

    def _load_json(self):
        """Loads a JSON file or all JSON files in a folder and returns a dictionary."""
        data = {}
        if self.path.is_file() and self.path.suffix == ".json":
            self._load_single_file(self.path, data)
        elif self.path.is_dir():
            for json_file in sorted(self.path.glob("*.json")):
                self._load_single_file(json_file, data)
        return data

    def _load_single_file(self, file_path, data):
        """Loads a single JSON file and adds its content to the data dictionary."""
        with open(file_path, "r", encoding="utf-8") as file:
            try:
                content = json.load(file)
                data[file_path] = content  # Store JSON content under its filename
            except json.JSONDecodeError as e:
                log(
                    f"{self.__class__.__name__}: Error parsing {file_path}: {e}",
                    force=True,
                )

    def write_json(self, content):
        """
        Writes JSON content to a file, ensuring indentation and error handling.
        """
        try:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(content, file, indent=4)
        except IOError as e:
            log(
                f"{self.__class__.__name__}: Error updating JSON file '{self.path}' --> {e}",
                force=True,
            )
        else:
            log(
                f"{self.__class__.__name__}: JSON file '{self.path}' updated successfully."
            )

    def validate_json(self, content):
        """Validates JSON structure (basic check)."""
        try:
            json.dumps(content)  # Check if serializable
            return True
        except (TypeError, ValueError):
            return False


class JSONMerger:
    """
    Lazily merges multiple JSON files from different directories by yielding individual elements.
    Ensures that all files contain a valid "mapping" key before processing.
    """

    def __init__(self, base_folder, subfolders, grouping_key=None):
        """Initializes the merger with a base folder and list of subfolders to load JSON from."""
        self.base_folder = base_folder
        self.subfolders = subfolders
        self.grouping_key = grouping_key

    def _merge_json_files(self, folder_path):
        json_handler = JSONHandler(folder_path)
        for file_path, content in json_handler.data.items():
            if self.grouping_key:
                key = content.get(self.grouping_key)
                if not key:
                    log(
                        f"{self.__class__.__name__}: Missing '{self.grouping_key}' key in {file_path}. Skipping file."
                    )
                    continue
                yield key, content
            else:
                yield from content.items()
        
    def get_merged_data(self):
        """
        Generator that merges JSON elements across subfolders lazily.
        Instead of loading all data at once, it yields one mapping at a time.
        """
        for subfolder in self.subfolders:
            folder_path = Path(self.base_folder) / subfolder
            for mapping, content in self._merge_json_files(folder_path):
                yield mapping, content

    def get_mapping(self, mapping_name):
        """Returns a generator that yields only data for a specific mapping."""
        return (
            content
            for mapping, content in self.get_merged_data()
            if mapping == mapping_name
        )
