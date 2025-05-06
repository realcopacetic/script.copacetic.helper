# author: realcopacetic

import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import cached_property, wraps
from pathlib import Path

from resources.lib.shared.utilities import log


def xml_functions(func):
    """
    Decorator to handle common XML transformation arguments.
    Retrieves root_tag, element_tag, and transform_func from kwargs
    and injects them before the decorated method is called.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        root_tag = kwargs.get("root_tag", self.root_tag)
        element_tag = kwargs.get("element_tag")
        sub_element_tag = kwargs.get("sub_element_tag")
        transform_func = kwargs.get("transform_func")

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
                "element_tag": element_tag,
                "sub_element_tag": sub_element_tag,
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

    def __init__(self, path, root_tag="includes"):
        """
        Initializes the handler with a file path and default root element.

        :param path: Path to the target XML file.
        :param root_tag: Root tag name used when creating new XML.
        """
        self.path = Path(path)
        self.root_tag = root_tag
        self._data = None

    @property
    def data(self):
        """
        Lazily loads and returns data from the specified path.

        :returns: Dictionary of {Path: content}.
        """
        if self._data is None:
            self._data = self._read_xml()
        return self._data

    @xml_functions
    def write_xml(self, data_dict, **kwargs):
        """
        Writes an XML file using the specified transform function and dictionary data.

        :param data_dict: Dictionary to convert into XML elements.
        :param kwargs: Configuration arguments, including `transform_func`, `root_tag`, etc.
        """
        try:
            tree = ET.ElementTree(
                kwargs["transform_func"](data_dict, **kwargs)
            )
            self._save_xml(tree)
        except Exception as e:
            log(f"{self.__class__.__name__}: ERROR writing XML --> {e}", force=True)

    @xml_functions
    def update_xml(self, updates, **kwargs):
        """
        Modifies or adds elements in an existing XML file using transformation settings.

        :param updates: Dictionary of key → value updates to apply.
        :param kwargs: Includes transform_func, root_tag, element_tag, etc.
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
                    f".//{kwargs['element_tag']}[@name='{key}']"
                )
                if existing_element is not None:
                    existing_element.text = value  # Modify existing element
                else:
                    ET.SubElement(target_root, kwargs["element_tag"], name=key).text = (
                        value  # Add new element
                    )

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
        if not self.path.exists():
            return {}

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

    def _create_new_xml(self, root_tag, element_tag, default_structure=None):
        """
        Creates and saves a new XML file with the specified structure.

        :param root_tag: Root element tag name.
        :param element_tag: Child tag name for each item in the structure.
        :param default_structure: Optional dictionary of name → text value.
        :returns: ElementTree instance.
        """
        root = ET.Element(root_tag)
        default_structure = default_structure or {}

        for key, value in default_structure.items():
            ET.SubElement(root, element_tag, name=key).text = value

        tree = ET.ElementTree(root)
        self._save_xml(tree)
        log(
            f"{self.__class__.__name__}: Created new XML file '{self.path}' with root '{root_tag}'."
        )
        return tree

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

    @staticmethod
    def _simple_dict_to_xml(data_dict, **kwargs):
        """
        Converts flat or nested dictionaries into a Kodi-compatible XML Element.

        :param data_dict: Dictionary containing flat or nested data structures.
        :param kwargs: Includes optional `root_tag`, `element_tag`, and `sub_element_tag`.
        :returns: XML root Element built from dictionary data.
        """
        root_tag = kwargs.get("root_tag", "includes")
        element_tag = kwargs.get("element_tag", "variable")
        sub_element_tag = kwargs.get("sub_element_tag", "value")
        root = ET.Element(root_tag)

        for outer_key, outer_value in data_dict.items():
            # Flat structure
            if isinstance(outer_value, str):
                ET.SubElement(root, element_tag, name=outer_key).text = outer_value
            # Nested structure
            elif isinstance(outer_value, list) and all(
                isinstance(item, dict) for item in outer_value
            ):
                outer_elem = ET.SubElement(root, element_tag, name=outer_key)
                for item in outer_value:
                    sub_elem = ET.SubElement(outer_elem, sub_element_tag)
                    for attr, val in item.items():
                        if attr == "value":
                            sub_elem.text = val
                        else:
                            sub_elem.set(attr, val)
            else:
                log(
                    f"XMLHandler: Unsupported data type for '{outer_key}': {type(outer_value)}",
                    force=True,
                )

        return root

    @staticmethod
    def _complex_dict_to_xml(data_dict, **kwargs):
        """
        Converts structured dictionaries from XMLDictConverter back into XML elements.

        :param data_dict: Structured dictionary to convert back to XML.
        :param kwargs: Optional XML configuration arguments (e.g., `root_tag`).
        :returns: XML root Element representing structured dictionary data.
        """
        converter = XMLDictConverter(None, **kwargs)
        return converter.dict_to_xml(data_dict)


class XMLMerger:
    """
    Merges XML files across multiple folders grouped by their <mapping> tags.
    Outputs a single aggregated ET.Element per mapping.
    """

    def __init__(self, base_folder, subfolders=None, **read_kwargs):
        """
        Initialises class with kwargs passed from BUILDER_CONFIG for each
        individual xml builder.

        :param base_folder: Base directory containing XML subfolders.
        :param subfolders: List of subfolders to search and merge XML from.
        :param read_kwargs: Keyword arguments defining XML structure tags.
        """
        self.base_folder = Path(base_folder)
        self.subfolders = subfolders or []
        self.root_tag = read_kwargs.get("root_tag", "xml")
        self.container_tag = read_kwargs.get("container_tag", "includes")
        self.element_tag = read_kwargs.get("element_tag", "template")

    def _merge_xml_files(self, folder_path):
        """
        Lazily merges XML elements from a single folder.

        :param folder_path: Path to a subfolder containing XML files.
        :yields: Tuples of (mapping_name, ET.Element).
        """
        xml_handler = XMLHandler(folder_path)
        for file_path, tree in xml_handler.data.items():
            root = tree.getroot()
            mapping_name = root.findtext("mapping", "none").strip()
            container = root.find(self.container_tag)
            if container is None:
                log(f"{self.__class__.__name__}: No container <{self.container_tag}> in {file_path}. Skipping file.")
                continue
            elements = container.findall(self.element_tag)
            yield mapping_name, elements

    def yield_merged_data(self):
        """
        Lazily yields aggregated XML elements merged by mapping names.

        :yields: Tuples of (mapping_name, merged ET.Element).
        """
        mappings = defaultdict(list)
        for subfolder in self.subfolders:
            folder_path = self.base_folder / subfolder
            if not folder_path.exists():
                log(f"{self.__class__.__name__}: Folder {folder_path} does not exist. Skipping.")
                continue
            for mapping_name, elements in self._merge_xml_files(folder_path):
                mappings[mapping_name].extend(elements)

        for mapping, elements in mappings.items():
            yield mapping, self._build_merged_xml(mapping, elements)

    def _build_merged_xml(self, mapping, elements):
        """
        Builds a single merged ET.Element for a given mapping.

        :param mapping: The mapping name for the XML elements.
        :param elements: List of ET.Elements to merge.
        :returns: Merged ET.Element.
        """
        merged_root = ET.Element(self.root_tag)
        merged_mapping = ET.SubElement(merged_root, "mapping")
        merged_mapping.text = mapping
        merged_container = ET.SubElement(merged_root, self.container_tag)
        merged_container.extend(elements)
        return merged_root

    @cached_property
    def cached_merged_data(self):
        """
        Eagerly loads and caches all XML mappings as a dictionary.
        Useful for random access or repeated lookups.

        :returns: Dictionary of {mapping_key: content}
        """
        return dict(self.yield_merged_data())


class XMLDictConverter:
    """
    Converts between XML ElementTrees and structured dictionaries.
    """

    ATTR_PREFIX = "@"
    TEXT_KEY = "#text"

    def __init__(self, root_element, **kwargs):
        """
        Initialises class with kwargs passed from BUILDER_CONFIG for each
        individual xml builder.

        :param root_element: Root element of the XML to convert.
        :param read_kwargs: XML parsing options (container and element tags).
        """
        self.root = root_element
        self.root_tag = kwargs.get("root_tag")
        self.container_tag = kwargs.get("container_tag", self.root_tag)
        self.element_tag = kwargs.get("element_tag")
        self.mapping_tag = kwargs.get("mapping_tag")
        self.template_tag = kwargs.get("template_tag")
        self.sub_element_tag = kwargs.get("sub_element_tag")

    def xml_to_dict(self):
        """
        Converts an XML tree into a structured dictionary.

        :returns: Structured dictionary representation of the XML.
        """
        output_dict = {
            self.mapping_tag: self.root.findtext(self.mapping_tag, default="none").lower(),
            self.container_tag: {},
        }

        container = self.root.find(self.container_tag)
        if container is None:
            log(
                f"{self.__class__.__name__}: Missing container tag <{self.container_tag}>.",
                force=True,
            )
            return output_dict

        for element in container.findall(self.element_tag):
            template_dict = {}

            expansion_elem = element.find("expansion")
            index_elem = element.find("index")
            items_elem = element.find("items")

            if expansion_elem is not None:
                template_dict["expansion"] = expansion_elem.text.strip()

            if index_elem is not None:
                template_dict["index"] = {
                    f"{self.ATTR_PREFIX}start": index_elem.get("start", "1")
                }
                if index_elem.get("end"):
                    template_dict["index"][f"{self.ATTR_PREFIX}end"] = index_elem.get("end")

            if items_elem is not None:
                items = [item.strip() for item in items_elem.text.split(",")]
                template_dict["items"] = items

            include_elem = element.find(self.sub_element_tag)
            if include_elem is None or "name" not in include_elem.attrib:
                log(
                    f"{self.__class__.__name__}: Missing or invalid {self.sub_element_tag} tag in element.",
                    force=True,
                )
                continue

            template_key = include_elem.get("name")

            try:
                include_dict = self.element_to_dict(include_elem)
                template_dict[self.sub_element_tag] = include_dict[self.sub_element_tag]
                template_dict[self.sub_element_tag][f"{self.ATTR_PREFIX}name"] = template_key

                output_dict[self.container_tag][template_key] = template_dict

            except Exception as e:
                log(
                    f"{self.__class__.__name__}: Error processing element '{template_key}' → {e}",
                    force=True,
                )
                continue

        return output_dict

    def element_to_dict(self, element):
        """
        Recursively converts an XML element into a dictionary.

        :param element: XML element to convert.
        :returns: Dictionary representation of the element.
        """
        node_dict = {element.tag: {} if element.attrib or list(element) else ""}

        for attr, val in element.attrib.items():
            node_dict[element.tag][f"{self.ATTR_PREFIX}{attr}"] = val

        children = list(element)

        if children:
            child_dict = defaultdict(list)
            for child in children:
                child_data = self.element_to_dict(child)
                tag, value = next(iter(child_data.items()))
                child_dict[tag].append(value)

            for tag, values in child_dict.items():
                # Always wrap certain tags (like "param" and "include") in a list, even if
                # there is only one element. This simplifies downstream template expansion
                # and parameter substitution logic by ensuring consistent handling.
                if tag in {"param", "include"}:
                    node_dict[element.tag][tag] = values
                else:
                    node_dict[element.tag][tag] = (
                        values if len(values) > 1 else values[0]
                    )

        text = (element.text or "").strip()
        if text:
            if children or element.attrib:
                node_dict[element.tag][self.TEXT_KEY] = text
            else:
                node_dict[element.tag] = text

        return node_dict

    def dict_to_xml(self, data_dict):
        """
        Converts a structured dictionary back into an XML Element,
        explicitly handling lists to avoid unwanted wrappers.

        :param data_dict: Structured dictionary to convert.
        :param root_tag: Tag name for the root XML element.
        :returns: XML Element representing the structured dictionary.
        """
        root_elem = ET.Element(self.root_tag)

        for key, value in data_dict.items():
            try:
                if isinstance(value, dict):
                    for inner_key, inner_value in value.items():
                        if isinstance(inner_value, list):
                            # Explicitly handle lists at the top level
                            for item in inner_value:
                                child_elem = self.dict_to_element({inner_key: item})
                                root_elem.append(child_elem)
                        else:
                            child_elem = self.dict_to_element({inner_key: inner_value})
                            root_elem.append(child_elem)
                elif isinstance(value, list):
                    for item in value:
                        child_elem = self.dict_to_element({key: item})
                        root_elem.append(child_elem)
                else:
                    child_elem = self.dict_to_element({key: value})
                    root_elem.append(child_elem)

            except Exception as e:
                log(
                    f"{self.__class__.__name__}: Error converting '{key}' → {e}", force=True
                )

        return root_elem

    def dict_to_element(self, data, parent_tag=None):
        """
        Recursively converts dictionary elements into XML elements without
        creating extra wrapper tags for lists.

        :param data: Dictionary to convert into XML.
        :param parent_tag: Optional parent XML tag.
        :returns: XML Element representing the dictionary entry.
        """
        if not isinstance(data, dict):
            elem = ET.Element(parent_tag or "item")
            elem.text = str(data)
            return elem

        tag = parent_tag or next(iter(data))
        elem_data = data if parent_tag else data[tag]

        elem = ET.Element(tag)

        if isinstance(elem_data, dict):
            for k, v in elem_data.items():
                if k.startswith(self.ATTR_PREFIX):
                    elem.set(k[len(self.ATTR_PREFIX):], v)
                elif k == self.TEXT_KEY:
                    elem.text = v
                elif isinstance(v, list):
                    for child_item in v:
                        child = self.dict_to_element({k: child_item})
                        elem.append(child)
                else:
                    child = self.dict_to_element({k: v})
                    elem.append(child)
        elif isinstance(elem_data, list):
            for item in elem_data:
                child = self.dict_to_element(item, parent_tag=tag)
                elem.append(child)
        elif elem_data != "":
            elem.text = str(elem_data)

        return elem
