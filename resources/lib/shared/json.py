# author: realcopacetic

import json
from functools import cached_property
from pathlib import Path

from resources.lib.shared.utilities import log


class JSONHandler:
    """
    Loads, validates, and writes JSON files or all JSONs within a folder.
    Supports merging multiple JSON sources via filename-based keys.
    """

    def __init__(self, path):
        """
        Initializes the handler and loads content from a file or folder.

        :param path: Path to a JSON file or directory of JSON files.
        """
        self.path = Path(path)
        self._data = None

    @property
    def data(self):
        """
        Lazily loads and returns data from the specified path.

        :returns: Dictionary of {Path: content}.
        """
        if self._data is None:
            self._data = self._load_json()
        return self._data

    @property
    def exists(self):
        """
        Returns True if the target path (file or directory) exists.
        """
        return self.path.exists()

    def _load_json(self):
        """
        Loads one or more JSON files and returns a combined dictionary.

        :returns: Dictionary of {Path: content}.
        """
        if not self.path.exists():
            return {}

        data = {}
        if self.path.is_dir():
            # Handle directory, merge json files
            for json_file in sorted(self.path.glob("*.json")):
                self._load_single_file(json_file, data)
        else:
            # Handle single file
            self._load_single_file(self.path, data)
        return data

    def _load_single_file(self, file_path, data):
        """
        Parses a JSON file and updates the provided dictionary with the content.
        The dictionary is mutable and modified in place, so no explicit return value
        needs to be declared.

        :param file_path: Path to the .json file.
        :param data: Reference to dictionary to update with parsed content.
        """
        with open(file_path, "r", encoding="utf-8") as file:
            try:
                content = json.load(file)
                data[file_path] = content  # Store JSON content under its filename
            except json.JSONDecodeError as e:
                log(
                    f"{self.__class__.__name__}: Error parsing {file_path}: {e}",
                    force=True,
                )
        return

    def reload(self):
        """
        Forces a reload of the JSON data from disk.
        """
        self._data = self._load_json()

    def write_json(self, content):
        """
        Writes a JSON-serializable dictionary to disk with indentation.

        :param content: Data to be written to the current path.
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
        """
        Validates if the provided content is JSON-serializable.

        :param content: Python object to validate.
        :returns: True if valid, False otherwise.
        """
        try:
            json.dumps(content)  # Check if serializable
            return True
        except (TypeError, ValueError):
            return False


class JSONMerger:
    """
    Merges JSON files across multiple folders, supporting both lazy and eager access.
    Lazily yields mappings from multiple files or returns a cached dict for fast reuse.
    """

    def __init__(self, base_folder, subfolders, grouping_key=None):
        """
        Initializes the merger with folder structure and optional grouping key.

        :param base_folder: Root folder path.
        :param subfolders: List of subfolder names to search.
        :param grouping_key: Optional key to group data by (e.g., "mapping").
        """
        self.base_folder = base_folder
        self.subfolders = subfolders or []
        self.grouping_key = grouping_key

    def _merge_json_files(self, folder_path):
        """
        Lazily merges JSON data from a single folder.

        :param folder_path: Path to a subfolder containing JSON files.
        :yields: (grouping_key, content) or (key, value) pairs.
        """
        json_handler = JSONHandler(folder_path)
        for file_path, content in json_handler.data.items():
            if self.grouping_key:
                key = content.get(self.grouping_key)
                if not key:
                    log(
                        f"{self.__class__.__name__}: Missing '{self.grouping_key}' key in {file_path}. Skipping file."
                    )
                    continue
                filtered = {k: v for k, v in content.items() if k != self.grouping_key}
                yield key, filtered
            else:
                yield from content.items()

    def yield_merged_data(self):
        """
        Lazily yields all JSON mappings across the configured subfolders.
        Useful when processing data incrementally or working with large files.

        :yields: (mapping_key, content) tuples.
        """
        for subfolder in self.subfolders:
            folder_path = Path(self.base_folder) / subfolder
            for mapping, content in self._merge_json_files(folder_path):
                yield mapping, content

    @cached_property
    def cached_merged_data(self):
        """
        Eagerly loads and caches all JSON mappings as a dictionary.
        Useful for random access or repeated lookups.

        :returns: Dictionary of {mapping_key: content}
        """
        return dict(self.yield_merged_data())
