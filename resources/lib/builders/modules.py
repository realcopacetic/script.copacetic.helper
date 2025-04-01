# author: realcopacetic

from collections import defaultdict
from functools import wraps
from itertools import product

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import log
import xml.etree.ElementTree as ET


def expand_index(index_obj):
    """
    Expands a dict with start/end/step into a list of string indices.

    :param index_obj: Dictionary with "start", "end", and optional "step".
    :returns: List of stringified index values.
    """
    try:
        start = int(index_obj["start"])
        end = int(index_obj["end"]) + 1
        step = int(index_obj.get("step", 1))
        return [str(i) for i in range(start, end, step)]
    except (KeyError, TypeError, ValueError):
        return []


class BaseBuilder:
    """
    Base class for all builders that handles loop expansion and substitution logic.
    Used by all specialized builder types to generate template values.
    """

    def __init__(self, loop_values, placeholders, dynamic_key):
        """
        Initializes builder with placeholders, loop values, and dynamic key.

        :param loop_values: List or dict of content types or keys to loop over.
        :param placeholders: Dictionary of placeholder names for formatting.
        :param dynamic_key: Optional placeholder for nested dynamic values.
        """
        self.loop_values = loop_values
        log(f'FUCK loop_values {loop_values}')
        self.placeholders = placeholders
        self.dynamic_key = dynamic_key
        self.rules = RuleEngine()
        self.group_map = {}

    def process_elements(self, element_name, element_data):
        """
        Processes a template element by generating and expanding substitutions.

        :param element_name: The name of the expression/template.
        :param element_data: Data dict containing rules and item values.
        :returns: Generator yielding {name: value} dicts.
        """
        items = (
            element_data.get("items") or
            expand_index(element_data.get("index")) or
            self.loop_values
        )
        substitutions = self.generate_substitutions(items)

        yield from (
            {k: v}
            for k, v in self.group_and_expand(
                element_name, element_data, substitutions
            ).items()
        )

    def generate_substitutions(self, items):
        """
        Generates substitution dicts based on loop structure and items.

        :param items: List of items to loop over.
        :returns: List of substitution dictionaries.
        """
        key_name = self.placeholders.get("key")
        value_name = self.placeholders.get("value")

        if isinstance(self.loop_values, dict):
            if not key_name or not value_name:
                raise ValueError(
                    "Missing 'key' or 'value' in placeholders for dict-based loop_values"
                )

            return [
                {
                    key_name: outer_key,
                    value_name: inner_value,
                    **({self.dynamic_key: item} if self.dynamic_key else {}),
                }
                for outer_key, inner_values in self.loop_values.items()
                for inner_value, item in product(inner_values, items)
            ]

        elif isinstance(self.loop_values, list):
            return [
                {key_name: loop_value, self.dynamic_key: item}
                for loop_value, item in product(self.loop_values, items)
            ]

        else:
            return [{self.dynamic_key: item} for item in items]

    def substitute(self, string, substitutions):
        """
        Formats a string using the provided substitution dictionary.

        :param string: Template string with placeholders.
        :param substitutions: Dict of key-value substitutions.
        :returns: Fully formatted string.
        """
        return string.format(**substitutions)


class controlsBuilder(BaseBuilder):
    """
    Builder that generates fully expanded control definitions.
    Expands placeholders, assigns IDs, and resolves update triggers.
    """

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups and expands control definitions by key and type.

        :param template_name: Control name template
        :param data: Control definition template
        :param substitutions: List of substitution dictionaries
        :returns: Dict of {control_name: resolved_definition}
        """
        id_start = data.get("id_start")
        id_fixed = data.get("id")

        # Dynamic controls
        if "dynamic_linking" in data:
            resolved_list = []
            seen = set()
            for sub in substitutions:
                resolved = {
                    field: self.substitute(value, sub)
                    for field, value in data["dynamic_linking"].items()
                    if isinstance(value, str)
                }
                key = tuple(sorted(resolved.items()))
                if key not in seen:
                    seen.add(key)
                    resolved_list.append(resolved)

            return {
                template_name: {
                    **{
                        k: v
                        for k, v in data.items()
                        if k not in ("dynamic_linking", "id")
                    },
                    "id": id_fixed,
                    "dynamic_linking": resolved_list,
                }
            }
        # Static controls
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        return {
            key: self.resolve_values(subs[0], data, id_start, i)
            for i, (key, subs) in enumerate(grouped.items())
        }

    def resolve_values(self, sub, data, id_start, index):
        """
        Resolves fields for a flat (non-dynamic) control.

        :param sub: Substitution dict
        :param data: Control template
        :param id_start: Optional starting ID
        :param index: Index for control ID
        :returns: Resolved control dict
        """
        resolved = {
            field: self.substitute(value, sub)
            for field, value in data.items()
            if isinstance(value, str)
        }
        for field, value in data.items():
            if not isinstance(value, str):
                resolved[field] = value

        if id_start is not None:
            resolved["id"] = id_start + index

        return resolved


class expressionsBuilder(BaseBuilder):
    """
    Builder that processes expression definitions by expanding all possible
    variations and handles conditional logic.
    """

    def process_elements(self, element_name, element_data):
        """
        Overrides BaseBuilder class, calling super().process_elements then
        applying fallback logic after substitution.

        :param element_name: Expression name template.
        :param element_data: Dictionary of rule definitions and items.
        :returns: Generator yielding final expression dict.
        """
        resolved = {}
        for d in super().process_elements(element_name, element_data):
            resolved.update(d)

        yield self._apply_fallbacks(resolved, element_data)

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups substitutions and resolves values based on expression rules.

        :param template_name: Expression key pattern with placeholders.
        :param data: Raw template and rule data.
        :param substitutions: List of substitution dicts.
        :returns: Dictionary of {expression_key: expression_value}.
        """
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        return {
            key: " | ".join(resolved) if resolved else None
            for key, subs in grouped.items()
            for resolved in [self.resolve_values(subs, data)]
        }

    def resolve_values(self, subs, data):
        """
        Resolves rules for each substitution group and returns values.

        :param subs: List of substitution dictionaries for one group.
        :param data: Template rule data.
        :returns: List of expression values (or "false" fallback).
        """
        resolved = []
        rules = data.get("rules", [])

        for sub in subs:
            for rule in rules:
                condition = rule["condition"].format(**sub)

                if not self.rules.evaluate(condition):
                    continue

                value = rule["value"].format(**sub)

                if rule["type"] == "assign":
                    return [value]  # short-circuit with override
                elif rule["type"] == "append":
                    resolved.append(value)
                else:
                    raise ValueError(f"Unsupported rule type: {rule['type']}")
        return resolved if resolved else ["false"]

    def _apply_fallbacks(self, resolved, expr_data):
        """
        Applies fallback values to expression groups when needed.

        :param resolved: Dict of resolved expressions.
        :param expr_data: The expression's full rule definition.
        :returns: Updated resolved expression dict with fallbacks applied.
        """
        fallback_key = next(
            (k for k in expr_data if k.startswith("fallback_for_")), None
        )
        if not fallback_key:
            return resolved

        fallback_field = fallback_key.replace("fallback_for_", "").strip("{}")
        fallback_values = expr_data[fallback_key].get("fallback_values", [])
        fallback_items = (
            expr_data[fallback_key].get("fallback_items", []) or fallback_values
        )

        all_exprs_by_group = defaultdict(list)
        for expr_name in resolved:
            sub = self.group_map.get(expr_name, {})
            if fallback_field in sub:
                all_exprs_by_group[sub[fallback_field]].append(expr_name)

        for i, (group_key, expr_list) in enumerate(all_exprs_by_group.items()):
            fallback_item = fallback_items[min(i, len(fallback_items) - 1)]
            fallback_value = fallback_values[min(i, len(fallback_values) - 1)]

            if not expr_list:
                continue

            target_expr = next(
                (
                    name
                    for name in expr_list
                    if self.group_map[name].get("item") == fallback_item
                ),
                None,
            )

            if not target_expr:
                log(
                    f"{self.__class__.__name__}: [Fallback skipped] No match for fallback_item '{fallback_item}' in group '{group_key}'",
                )
                continue

            others = {
                name: resolved[name]
                for name in expr_list
                if self.group_map[name].get("item") != fallback_item
                and resolved.get(name) not in ("false", None)
            }

            resolved[target_expr] = (
                self.rules.invert(others)
                if fallback_value in ("invert()", "{invert}")
                else fallback_value
            ) or "true"

            log(
                f"{self.__class__.__name__}: [Fallback applied] {target_expr} = {resolved[target_expr]} (group: {group_key}, others: {list(others.keys())})",
            )

        return resolved


class skinsettingsBuilder(BaseBuilder):
    """
    Builder that resolves UI skinsettings based on exclusion/inclusion rules.
    """

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups and evaluates skinsetting options based on filtering logic.

        :param template_name: Template name for setting key.
        :param data: Rule and items data.
        :param substitutions: List of dicts for placeholder substitution.
        :returns: Dictionary of setting key → {items: [...]}
        """
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        return {key: self.resolve_values(subs, data) for key, subs in grouped.items()}

    def resolve_values(self, subs, data):
        """
        Resolves filtered setting values based on rule conditions.

        :param subs: List of substitutions for a single setting group.
        :param data: Full setting definition, including filter_mode and rules.
        :returns: Dict of final filtered items.
        """
        items = data.get("items", [])
        filter_mode = data.get("filter_mode", "exclude")
        rules = data.get("rules", [])

        excluded = set()
        for sub in subs:
            for rule in rules:
                condition = rule.get("condition", "").format(**sub)
                values = rule.get("value", [])

                if self.rules.evaluate(condition):
                    excluded.update(values)

        if filter_mode == "exclude":
            final_items = [item for item in items if item not in excluded]
        else:
            final_items = [item for item in items if item in excluded]

        return {"items": final_items}


class variablesBuilder(BaseBuilder):
    """
    Builder that generates Kodi-style variable definitions with condition/value pairs.
    """

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups variable templates and resolves multiple indexed variations.

        :param template_name: Template for variable name.
        :param data: Rule and value definitions for the variable.
        :param substitutions: List of substitution dicts.
        :returns: Dictionary of variable name → value list.
        """
        grouped = defaultdict(list)

        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        return {
            variable["name"]: variable["values"]
            for subs in grouped.values()
            for variable in self.resolve_values(template_name, subs, data)
        }

    def resolve_values(self, template_name, subs, data):
        """
        Builds one or more variables from template and substitutions.

        :param template_name: Name pattern of variable.
        :param subs: Substitution set for this group.
        :param data: Variable definition including values and index.
        :returns: List of variable dicts with name and condition/value pairs.
        """
        values = data.get("values", [])
        index_range = expand_index(data.get("index"))

        if not index_range:
            name = self.substitute(template_name, subs[0])
            return [self._build_variable(name, values, subs[0])]

        return [
            self._build_variable(
                self.substitute(template_name, {**subs[0], "index": str(i)}),
                values,
                {**subs[0], "index": str(i)},
            )
            for i in index_range
        ]

    def _build_variable(self, name, values, subs):
        """
        Creates a variable dict with condition/value mappings from template.

        :param name: Fully formatted variable name.
        :param values: List of condition/value template pairs.
        :param subs: Substitution dictionary for formatting.
        :returns: Dict with 'name' and resolved 'values' list.
        """
        return {
            "name": name,
            "values": [
                {
                    "condition": self.substitute(v.get("condition", ""), subs),
                    "value": self.substitute(v.get("value", ""), subs),
                }
                for v in values
            ],
        }


class xmlBuilder(BaseBuilder):
    """
    XML-specific builder that processes XML-based elements and applies
    the same logic as BaseBuilder but with XML-specific conversion.
    """

    def convert_xml_to_dict(self, element):
        """
        Converts XML element data into a dictionary for easier processing.
        Handles placeholders like {metadata:xyz} for later substitution.
        """
        if isinstance(element, ET.Element):
            # Build a dictionary of the XML structure
            return {element.tag: {child.tag: child.text for child in element}}
        return {}

    def process_elements(self, element_name, element_data):
        """
        Processes the XML element by generating substitutions and grouping
        them into the desired format.
        :param element_name: The name of the expression/template.
        :param element_data: Data dict containing rules and item values.
        :returns: Generator yielding {name: value} dicts.
        """
        # If the data is XML, convert it into a dictionary
        if isinstance(element_data, ET.Element):
            element_data = self.convert_xml_to_dict(element_data)

        # Use the inherited process_elements logic from BaseBuilder
        yield from super().process_elements(element_name, element_data)

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups and expands the XML-specific elements by key and type,
        allowing for dynamic key substitution and expansion.

        :param template_name: The name of the XML element to process.
        :param data: Data related to the XML element.
        :param substitutions: List of substitutions to apply.
        :returns: Expanded XML data as dictionary.
        """
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        # Reconstruct the elements as necessary, using the groupings
        return {key: self.resolve_values(subs, data) for key, subs in grouped.items()}

    def resolve_values(self, subs, data):
        """
        Resolves and processes the values for the XML structure.
        - Handles {metadata:xyz} substitutions
        :param subs: The substitution dictionary.
        :param data: The XML element data.
        :returns: The resolved values.
        """
        resolved = {}
        for sub in subs:
            # Substitute placeholders with values (including {metadata:xyz})
            resolved[sub] = self.substitute(data, sub)

        return resolved

    def substitute(self, string, substitutions):
        """
        Custom substitution logic to handle both {key} and {metadata:xyz} tags.
        :param string: The string to substitute placeholders in.
        :param substitutions: The substitutions to apply.
        :returns: The substituted string.
        """
        # First substitute for placeholders like {key} or {item}
        result = string.format(**substitutions)

        # Now handle {metadata:xyz} by checking if it's part of the substitutions
        result = self.handle_metadata_tags(result)

        return result

    def handle_metadata_tags(self, string):
        """
        Handles metadata tags like {metadata:xyz} and substitutes them from the mappings.
        :param string: The string with potential {metadata:xyz} placeholders.
        :returns: The string with metadata tags substituted.
        """
        import re

        # Find all {metadata:xyz} tags in the string
        metadata_pattern = r"{metadata:(\w+)}"
        matches = re.findall(metadata_pattern, string)

        for match in matches:
            # Replace {metadata:xyz} with the corresponding value from mappings
            if match in self.placeholders:
                string = string.replace(
                    f"{{metadata:{match}}}", self.placeholders[match]
                )

        return string
