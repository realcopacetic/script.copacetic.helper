# author: realcopacetic

import xml.etree.ElementTree as ET

from resources.lib.utilities import log, LOOKUP_XML


class XMLHandler:
    def __init__(self):
        self.lookup = LOOKUP_XML
        self._cached_lookup = None
        self._force_read = False
        self._force_write = False
        self._instance_id = id(self)  # Unique identifier for each instance

    def get_root(self):
        log(f"Using XMLHandler instance ID: {self._instance_id}", force=True)
        # Only reparse XML if it has not been cached or if forced to after a write.
        if self._cached_lookup is None or self._force_read:
            try:
                self._cached_lookup = ET.parse(self.lookup)
                log(f'Parsing _lookup.xml file')
            except (ET.ParseError, IOError) as e:
                log(f'Error parsing _lookup.xml file --> {e}', force=True)
            else:
                self._force_read = False
        return self._cached_lookup

    def add_sub_element(self, parent_element, tag_name, attributes):
        # Build a new sub element in the XML file ready for writing
        sub_element = ET.SubElement(parent_element, tag_name)
        for key, value in attributes.items():
            sub_element.attrib[key] = value
        self._force_write = True
        return sub_element

    def write(self):
        # Write to xml file then set flag to ensure updated file is reparsed on next load
        if self._force_write:
            try:
                self._cached_lookup.write(self.lookup, encoding="utf-8")
            except IOError as e:
                log(f'Error writing to _lookup.xml file --> {e}', force=True)
            else:
                self._force_read = True
                self._force_write = False
                log(f'Writing new element(s) to _lookup.xml file')
