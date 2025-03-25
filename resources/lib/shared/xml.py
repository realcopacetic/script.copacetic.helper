# author: realcopacetic

import xml.etree.ElementTree as ET
from resources.lib.shared.utilities import log, validate_path
from functools import wraps


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

        if not self._file_exists():
            log(
                f"{self.__class__.__name__}: File '{self.file_path}' not found, creating a new one."
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

    def __init__(self, file_path, root_element="includes"):
        """
        Initializes the handler with a file path and default root element.

        :param file_path: Path to the target XML file.
        :param root_element: Root tag name used when creating new XML.
        """
        self.file_path = file_path
        self.root_element = root_element

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
                    f"XML file '{self.file_path}' not found, creating a new one.",
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

    def _file_exists(self):
        """
        Checks if the XML file exists and is valid.

        :returns: True if file exists and is accessible.
        """
        return validate_path(self.file_path)

    def _read_xml(self):
        """
        Parses and returns the current XML tree from file if it exists.

        :returns: ElementTree instance or None on error.
        """
        if not self._file_exists():
            return None

        try:
            with open(self.file_path, "rb") as file:
                return ET.parse(file)
        except (ET.ParseError, IOError) as e:
            log(
                f"{self.__class__.__name__}: Error parsing XML file --> {e}", force=True
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
            f"{self.__class__.__name__}: Created new XML file '{self.file_path}' with root '{root_tag}'."
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
            with open(self.file_path, "wb") as file:
                ET.indent(tree, space="  ")  # Ensures properly formatted XML
                tree.write(file, encoding="utf-8", xml_declaration=True)
        except IOError as e:
            log(
                f"{self.__class__.__name__}: Error updating XML file --> {e}",
                force=True,
            )
        else:
            log(
                f"{self.__class__.__name__}: XML file '{self.file_path}' updated successfully."
            )
