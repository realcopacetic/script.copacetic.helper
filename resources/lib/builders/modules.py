# author: realcopacetic

from collections import defaultdict

from resources.lib.builders.logic import RuleEngine, PlaceholderResolver
from resources.lib.shared.utilities import log


def ensure_list(value):
    """Ensure the value is always treated as a list."""
    return value if isinstance(value, list) else [value]


def get_fallback_entry(fallback_list, index, default="false"):
    """Returns the correct fallback entry (item or value), ensuring safe indexing."""
    return (
        fallback_list[min(index, len(fallback_list) - 1)] if fallback_list else default
    )


class BaseBuilder:
    """
    Base class for processing elements such as expressions, skin settings or controls.
    """

    def __init__(self, loop_values, placeholders):
        """
        Initializes BaseBuilder with loop structure and placeholders.

        :param loop_values: Dictionary or list defining the loop structure.
        :param placeholders: Mapping of placeholders for text substitution.
        """
        self.loop_values = loop_values
        self.placeholders = placeholders
        self.resolver = PlaceholderResolver(self.placeholders)
        self.rules = RuleEngine()

    def process_elements(self, element_name, element_data):
        """
        Iterates through elements based on the relevant looping values and yields results.

        :param element_name: Name of the element to process.
        :param element_data: Dictionary containing items, rules, and fallback settings.
        :yield: Dictionary of processed elements.
        """

        if isinstance(self.loop_values, dict):
            for loop_key, loop_items in self.loop_values.items():
                yield from self._resolve_element(
                    element_name, element_data, loop_key, loop_items
                )
        elif isinstance(self.loop_values, list):
            yield from self._resolve_element(
                element_name, element_data, None, self.loop_values
            )
        else:
            yield from self._resolve_element(element_name, element_data, None, None)

    def _resolve_element(self, element_name, element_data, loop_key, loop_values):
        """
        Resolves placeholders, applies fallback logic, and yields a processed dictionary dynamically.

        :param element_name: The name of the element.
        :param element_data: Dictionary with element details.
        :param loop_key: Outer loop key (if applicable, e.g., 'videos').
        :param loop_values: List of values from the inner loop (e.g., content types, widgets).
        :yield: A dictionary of processed expressions with fallback applied.
        """

        processed_results = defaultdict(set)
        placeholder_map = defaultdict(dict)

        for element_item in element_data.get("items", []):
            for inner_item in ensure_list(loop_values):

                placeholders = self.resolver.build_placeholders(
                    loop_key, inner_item, element_item
                )
                resolved = self.resolver.resolve(
                    {element_name: element_data}, placeholders
                )
                resolved_name, resolved_data = next(
                    iter(resolved.items()), (None, None)
                )
                value = self._process_single_element(resolved_data)
                processed_results[resolved_name].add(value if value else "false")

                placeholder_map[inner_item] = placeholders

        final_results = {
            key: " | ".join(values - {"false"}) if values - {"false"} else "false"
            for key, values in processed_results.items()
        }

        yield final_results, dict(placeholder_map)


class controlsBuilder(BaseBuilder):
    """
    Builds controls dynamically linked to skin settings for use in dynamic windows.
    """

    def _process_single_element(self, control_data):
        """ """
        ...

    def _resolve_element(self, control_name, control_data, loop_key, loop_values):
        """ """
        for processed_results, placeholders in super()._resolve_element(
            control_name, control_data, loop_key, loop_values
        ):
            yield dict(processed_results)


class expressionsBuilder(BaseBuilder):
    """
    Builds expressions defining visibility, inclusion, and logic for Kodi UI elements.
    """

    def _process_single_element(self, exp_data):
        """
        Evaluates conditions and constructs expression logic.

        :param exp_data: Dictionary containing rules, conditions, and fallback settings.
        :return: Dictionary of the processed expression.
        """
        values = []
        value = "false"

        for rule in exp_data.get("rules", []):
            condition = self.rules.evaluate(rule.get("condition"))

            if rule["type"] == "assign" and condition:
                value = rule.get("value")
                if value:  # Stop processing if we found a valid "assign"
                    break

            elif rule["type"] == "append" and condition:
                rule_value = ensure_list(rule.get("value"))
                values.extend(rule_value)

        else:  # Execute only if no early break for positive "assign" value
            if values:
                value = " | ".join(values)

        return value

    def _resolve_element(self, exp_name, exp_data, loop_key, loop_values):
        """
        Resolves expressions by calling `BaseBuilder._resolve_element()` first,
        then applies fallback logic specific to expressions.

        :param exp_name: The base name of the expression with placeholders (e.g., "views_{item}_{window}_include").
        :param exp_data: A dictionary containing items, rules and fallback conditions.
        :param loop_key: The parent key being iterated (e.g., "window") or None for list-based loops.
        :param loop_values: The values or list being iterated (e.g. "content_types" or "widgets").

        :yield: A dictionary mapping resolved expression names to their processed values.
        """

        for processed_results, placeholder_map in super()._resolve_element(
            exp_name, exp_data, loop_key, loop_values
        ):

            fallback_key = next(
                (k for k in exp_data if k.startswith("fallback_for_")), None
            )

            if fallback_key:
                placeholder = fallback_key.replace("fallback_for_", "")
                fallback_data = exp_data[fallback_key]
                fallback_values = fallback_data.get("fallback_values", [])
                fallback_items = fallback_data.get("fallback_items", [])

                # Handle inner loop wether it's a dictionary or list
                inner_loop_values = (
                    self.loop_values.get(loop_key, [])
                    if isinstance(self.loop_values, dict)
                    else self.loop_values
                )

                # Identify whether fallback value is from outer loop or inner loop
                index_override = None
                if isinstance(
                    self.loop_values, dict
                ) and placeholder in self.placeholders.get("key", []):
                    index_override = list(self.loop_values.keys()).index(loop_key)

                """
                For each inner loop iteration, resolve target expression and value.
                Even if fallback is for outer loop, we must do this because some
                fallback values are an inversion of the appended inner loop values
                """
                for index, inner_key in enumerate(inner_loop_values):
                    inner_placeholder_map = placeholder_map.get(inner_key, {})

                    if index_override is not None:
                        index = index_override

                    fallback_item = get_fallback_entry(fallback_items, index)
                    fallback_value = get_fallback_entry(
                        fallback_values, index, default="false"
                    )

                    resolved_fallback_target = (
                        exp_name.replace("{item}", fallback_item)
                        if fallback_item
                        else exp_name
                    )

                    for placeholder, value in inner_placeholder_map.items():
                        resolved_fallback_target = resolved_fallback_target.replace(
                            placeholder, value
                        )

                    if resolved_fallback_target in processed_results:
                        if fallback_value == "invert()":
                            processed_results[resolved_fallback_target] = (
                                self.rules.invert(
                                    {
                                        k: v
                                        for k, v in processed_results.items()
                                        if k != resolved_fallback_target
                                    }
                                )
                            )
                        else:
                            processed_results[resolved_fallback_target] = fallback_value
            yield dict(processed_results)


class skinsettingsBuilder(BaseBuilder):
    """
    Constructs simple map of allowed values for declared skin settings in a JSON file
    that can be used in dynamic settings windows to map settings to controls.
    """

    def _resolve_element(self, setting_name, setting_data, loop_key, loop_values):
        """
        Override BaseBuilder's _resolve_element method with a simpler loop to allow
        flatter processing of skin settings.

        :param element_name: The name of the element.
        :param element_data: Dictionary with element details.
        :param loop_key: Outer loop key (if applicable, e.g., 'videos').
        :param loop_values: List of values from the inner loop (e.g., content types, widgets).
        :yield: A dictionary of processed expressions with fallback applied.
        """
        for inner_item in ensure_list(loop_values):

            placeholders = self.resolver.build_placeholders(loop_key, inner_item)
            resolved = self.resolver.resolve({setting_name: setting_data}, placeholders)

            for resolved_setting_name, resolved_setting_data in resolved.items():
                processed_result = self._process_single_element(
                    resolved_setting_data, placeholders
                )
                yield {resolved_setting_name: processed_result}

    def _process_single_element(self, setting_data, placeholders):
        items = setting_data.get("items", [])
        rules = setting_data.get("rules", [])
        filter_mode = setting_data.get("filter_mode", "exclude")

        setting_type = "bool" if set(items).issubset({"true", "false"}) else "string"
        values = self._filter_items(items, rules, filter_mode)

        result = {"type": setting_type, "values": values}

        return {k: v for k, v in result.items() if v is not None}

    def _filter_items(self, items, rules, filter_mode):
        filtered_items = items.copy()

        for rule in rules:
            condition = rule["condition"]
            rule_values = rule["value"]

            if condition and self.rules.evaluate(condition):

                if filter_mode == "exclude":
                    filtered_items = [
                        item for item in filtered_items if item not in rule_values
                    ]
                elif filter_mode == "include":
                    filtered_items = [
                        item for item in filtered_items if item in rule_values
                    ]

        return filtered_items


class variablesBuilder(BaseBuilder):
    """
    Builds dynamic variable mappings based on Kodi skin expressions and settings.
    """

    def _resolve_element(self, var_name, var_data, loop_key, loop_values):
        """
        Generates structured variable XML mappings.
        """
        log(f"FUCK DEBUG: var_name {var_name}", force=True)
        log(f"FUCK DEBUG: var_data {var_data}", force=True)
        log(f"FUCK DEBUG: loop_key {loop_key}", force=True)
        log(f"FUCK DEBUG: loop_values {loop_values}", force=True)

        for processed_results in super()._resolve_element(
            var_name, var_data, loop_key, loop_values
        ):
            log(f"FUCK DEBUG: processed_results {processed_results}", force=True)
            yield processed_results
