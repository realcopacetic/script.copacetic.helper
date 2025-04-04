# author: realcopacetic

import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import cached_property, wraps
from pathlib import Path

from resources.lib.shared.utilities import log


def xml_functions(func):
    """
    Decorator to handle common XML transformation arguments.
    Retrieves root_tag, element_name, and transform_func from kwargs
    and injects them before the decorated method is called.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        root_tag = kwargs.get("root_tag", self.root_element)
        element_name = kwargs.get("element_name")
        sub_element_name = kwargs.get("sub_element_name")
        transform_func = kwargs.get("transform_func")

        if not self.path.exists():
            log(
                f"{self.__class__.__name__}: File '{self.path}' not found, creating a new one."
            )
            self._create_new_xml(root_tag, element_name)

        if not transform_func:
            log(
                f"{self.__class__.__name__}: ERROR - No transform function provided!",
                force=True,
            )
            return

        # Inject the retrieved parameters into kwargs before calling the original function
        kwargs.update(
            {
                "root_tag": root_tag,
                "element_name": element_name,
                "sub_element_name": sub_element_name,
                "transform_func": transform_func,
            }
        )
        return func(self, *args, **kwargs)

    return wrapper


class XMLHandler:
    """
    Handles reading, writing, and updating XML files using dynamic transformation logic.
    Supports structured transformations of flat or nested dictionary data into Kodi-compatible XML.
    """

    def __init__(self, path, root_element="includes"):
        """
        Initializes the handler with a file path and default root element.

        :param path: Path to the target XML file.
        :param root_element: Root tag name used when creating new XML.
        """
        self.path = Path(path)
        self.root_element = root_element
        self.data = self._read_xml()

    @xml_functions
    def write_xml(self, data_dict, **kwargs):
        """
        Writes a new XML structure from a dictionary using a transformation function.

        :param data_dict: Dictionary to be converted into XML.
        :param kwargs: Includes transform_func, root_tag, element_name, etc.
        """
        try:
            tree = ET.ElementTree(
                kwargs.get("transform_func")(
                    self,
                    kwargs.get("root_tag"),
                    data_dict,
                    element_name=kwargs.get("element_name"),
                    sub_element_name=kwargs.get("sub_element_name"),
                )
            )
            self._save_xml(tree)
        except Exception as e:
            log(f"{self.__class__.__name__}: ERROR writing XML --> {e}", force=True)

    @xml_functions
    def update_xml(self, updates, **kwargs):
        """
        Modifies or adds elements in an existing XML file using transformation settings.

        :param updates: Dictionary of key → value updates to apply.
        :param kwargs: Includes transform_func, root_tag, element_name, etc.
        """
        try:
            tree = self._read_xml()
            if tree is None:
                log(
                    f"XML file '{self.path}' not found, creating a new one.",
                    force=True,
                )
                self.write_xml(updates, **kwargs)
                return

            root = tree.getroot()

            # Find or create the correct root tag
            target_root = root.find(kwargs["root_tag"])
            if target_root is None:
                log(
                    f"{self.__class__.__name__}: Creating missing root tag '{kwargs['root_tag']}'."
                )
                target_root = ET.SubElement(root, kwargs["root_tag"])

            # Modify or add elements under the correct root
            for key, value in updates.items():
                existing_element = target_root.find(
                    f".//{kwargs['element_name']}[@name='{key}']"
                )
                if existing_element is not None:
                    existing_element.text = value  # Modify existing element
                else:
                    ET.SubElement(
                        target_root, kwargs["element_name"], name=key
                    ).text = value  # Add new element

            self._save_xml(tree)
        except Exception as e:
            log(f"{self.__class__.__name__}: ERROR updating XML --> {e}", force=True)

    def _read_xml(self):
        """
        Reads and returns the XML data. If the file path is a directory,
        merges XML files into a single tree, or returns a dictionary of trees if merging isn't possible.

        :returns: Dictionary of {file_name: ElementTree} if a folder,
                  or a single ElementTree if it's a file.
        """
        if self.path.is_dir():
            # Handle directory, merge XML files
            data = {}
            for xml_file in sorted(self.path.glob("*.xml")):
                tree = self._parse_single_xml(xml_file)
                if tree is not None:
                    data[xml_file.stem] = tree
            return data
        else:
            # Handle single file
            return self._parse_single_xml(self.path)

    def _parse_single_xml(self, file_path):
        """
        Parse a single XML file and return its ElementTree.

        :param file_path: Path to the XML file.
        :returns: ElementTree instance or None if the file doesn't exist or there is an error.
        """
        if not file_path.exists():
            log(
                f"{self.__class__.__name__}: File '{file_path}' does not exist.",
                force=True,
            )
            return None

        try:
            with open(file_path, "rb") as file:
                return ET.parse(file)
        except (ET.ParseError, IOError) as e:
            log(
                f"{self.__class__.__name__}: Error parsing XML file '{file_path}' --> {e}",
                force=True,
            )
            return None

    def _create_new_xml(self, root_tag, element_name, default_structure=None):
        """
        Creates and saves a new XML file with the specified structure.

        :param root_tag: Root element tag name.
        :param element_name: Child tag name for each item in the structure.
        :param default_structure: Optional dictionary of name → text value.
        :returns: ElementTree instance.
        """
        root = ET.Element(root_tag)
        default_structure = default_structure or {}

        for key, value in default_structure.items():
            ET.SubElement(root, element_name, name=key).text = value

        tree = ET.ElementTree(root)
        self._save_xml(tree)
        log(
            f"{self.__class__.__name__}: Created new XML file '{self.path}' with root '{root_tag}'."
        )
        return tree

    def _dict_to_xml(
        self,
        root_tag,
        data_dict,
        element_name="variable",
        sub_element_name="value",
        text_key="value",
    ):
        """
        Converts a dictionary into an XML tree, supporting both flat and nested formats.

        :param root_tag: XML root tag.
        :param data_dict: Dictionary to be converted.
        :param element_name: XML tag for main elements.
        :param sub_element_name: XML tag for nested value elements.
        :param text_key: Key to use as the inner text of sub-elements.
        :returns: Root Element.
        """
        root = ET.Element(root_tag)

        for outer_key, outer_value in data_dict.items():
            if isinstance(outer_value, str):
                # Flat structure
                ET.SubElement(root, element_name, name=outer_key).text = outer_value
            elif isinstance(outer_value, list) and all(
                isinstance(item, dict) for item in outer_value
            ):
                # Nested structure
                outer_elem = ET.SubElement(root, element_name, name=outer_key)
                for item in outer_value:
                    sub_elem = ET.SubElement(outer_elem, sub_element_name)
                    for attr, val in item.items():
                        if attr == "value":
                            sub_elem.text = val
                        else:
                            sub_elem.set(attr, val)
            else:
                log(
                    f"{self.__class__.__name__}: Unsupported data type for '{outer_key}': {type(outer_value)}",
                    force=True,
                )

        return root

    def _save_xml(self, tree):
        """
        Saves an ElementTree to disk with indentation and UTF-8 encoding.

        :param tree: XML ElementTree to write.
        :returns: None
        """
        try:
            with open(self.path, "wb") as file:
                ET.indent(tree, space="  ")  # Ensures properly formatted XML
                tree.write(file, encoding="utf-8", xml_declaration=True)
        except IOError as e:
            log(
                f"{self.__class__.__name__}: Error updating XML file --> {e}",
                force=True,
            )
        else:
            log(
                f"{self.__class__.__name__}: XML file '{self.path}' updated successfully."
            )


class XMLMerger:
    """
    Merges XML files across multiple folders, matching structure of JSONMerger.
    XML files must contain a <mapping> tag and a nested <elements> section.
    """

    def __init__(self, base_folder, subfolders=None):
        """
        Initializes the XML merger with the folder structure.

        :param base_folder: Root folder path containing builder subfolders.
        :param subfolders: List of subfolder names to search for XML files.
        """
        self.base_folder = Path(base_folder)
        self.subfolders = subfolders or []

    def _merge_xml_files(self, folder_path):
        """
        Merges XML files from a given folder path, grouping them by <mapping> tag.

        :param folder_path: Path to a subfolder containing XML files.
        :yields: (mapping_name, builder_data) tuples.
                 - mapping_name: The text content of the <mapping> tag.
                 - builder_data: Dictionary in the format { "xml": {name: Element, ...} }.
        """
        xml_handler = XMLHandler(folder_path)
        for path, tree in xml_handler.data.items():
            root = tree.getroot()

            mapping_tag = root.find("mapping")
            if mapping_tag is None or not mapping_tag.text:
                log(
                    f"{self.__class__.__name__}: Missing mapping key in {path}. Skipping file.",
                    force=True,
                )
                continue

            mapping_name = mapping_tag.text.strip()
            elements_root = root.find("elements")
            if elements_root is None:
                log(
                    f"{self.__class__.__name__}: Missing xml elements to be expanded in {path}. Skipping file.",
                    force=True,
                )
                continue

            converter = XMLDictConverter()
            builder_data = {
                "xml": {
                    elem.attrib["name"]: converter.element_to_dict(elem)
                    for elem in elements_root
                    if "name" in elem.attrib
                }
            }
            log(f"FUCK DEBUG {self.__class__.__name__}: builder_data {builder_data}")

            yield mapping_name, builder_data

    def yield_merged_data(self):
        """
        Lazily yields all XML mappings across the configured subfolders.

        :yields: (mapping_name, builder_data) tuples.
        """
        for subfolder in self.subfolders:
            folder_path = self.base_folder / subfolder
            if not folder_path.exists():
                continue
            yield from self._merge_xml_files(folder_path)

    @cached_property
    def cached_merged_data(self):
        """
        Eagerly loads and caches all XML mappings as a dictionary.

        :returns: Dictionary of {mapping_name: builder_data}
        """
        return dict(self.yield_merged_data())


class XMLDictConverter:
    ATTR_PREFIX = "@"
    TEXT_KEY = "#text"

    def element_to_dict(self, element):
        """
        Convert an ElementTree.Element to a nested dictionary.
        """
        
        node_dict = {element.tag: {} if element.attrib or list(element) else None}
        children = list(element)

        # Handle child elements
        if children:
            child_dict = defaultdict(list)
            for child in children:
                child_data = self.element_to_dict(child)
                tag, value = next(iter(child_data.items()))
                child_dict[tag].append(value)
            for tag, values in child_dict.items():
                node_dict[element.tag][tag] = values if len(values) > 1 else values[0]

        # Handle attributes
        for attr, val in element.attrib.items():
            node_dict[element.tag][f"{self.ATTR_PREFIX}{attr}"] = val

        # Handle text content
        text = (element.text or "").strip()
        if text:
            if children or element.attrib:
                node_dict[element.tag][self.TEXT_KEY] = text
            else:
                if element.tag == "items":
                    node_dict[element.tag] = [item.strip() for item in text.split(",")]
                else:
                    node_dict[element.tag] = text

        return node_dict

    def dict_to_element(self, data):
        """
        Convert a nested dictionary back into an ElementTree.Element.
        """

        def _build_element(tag, content):
            elem = ET.Element(tag)
            if isinstance(content, dict):
                for key, val in content.items():
                    if key.startswith(self.ATTR_PREFIX):
                        attr = key[len(self.ATTR_PREFIX) :]
                        elem.attrib[attr] = val
                    elif key == self.TEXT_KEY:
                        elem.text = val
                    elif isinstance(val, list):
                        for item in val:
                            child = _build_element(key, item)
                            elem.append(child)
                    else:
                        child = _build_element(key, val)
                        elem.append(child)
            elif isinstance(content, list) and tag == "items":
                elem.text = ", ".join(content)
            elif isinstance(content, str):
                elem.text = content
            return elem

        tag, content = next(iter(data.items()))
        return _build_element(tag, content)

    def pretty_print(self, element, indent="  "):
        """
        Pretty print an ElementTree.Element for debugging.
        """

        def _indent(elem, level=0):
            i = "\n" + level * indent
            if len(elem):
                if not elem.text or not elem.text.strip():
                    elem.text = i + indent
                for child in elem:
                    _indent(child, level + 1)
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
            else:
                if level and (not elem.tail or not elem.tail.strip()):
                    elem.tail = i

        _indent(element)
        return ET.tostring(element, encoding="unicode")
