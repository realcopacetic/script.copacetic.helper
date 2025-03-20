# author: realcopacetic

from collections import defaultdict
import functools

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


def wrap_with_element_items(func):
    """
    Decorator to iterate over `element_data.get("items", [])`
    and inject `element_item` into `build_placeholders`.
    """

    @functools.wraps(func)
    def wrapper(self, element_name, element_data, loop_key, loop_values):
        for element_item in element_data.get("items", []):
            yield from func(
                self, element_name, element_data, loop_key, loop_values, element_item
            )

    return wrapper


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
        Iterates through elements based on the relevant looping values and yields resolved results.

        :param element_name: Name of the element to process.
        :param element_data: Dictionary containing items, rules, and fallback settings.

        :yield: Dictionary of processed elements.
        """

        if isinstance(self.loop_values, dict):
            normalised_loop_values = self.loop_values
        elif isinstance(self.loop_values, list):
            normalised_loop_values = {None: self.loop_values}
        else:
            normalised_loop_values = {None: None}

        for loop_key, loop_items in normalised_loop_values.items():
            element_set = {}
            for data in self._resolve_element(
                element_name, element_data, loop_key, loop_items
            ):
                element_set.update(data)
            yield element_set

    def _resolve_element(
        self, element_name, element_data, loop_key, loop_values, element_item=None
    ):
        """
        Resolves placeholders, calls subclass processor logic, and yields a processed dictionary dynamically.

        :param element_name: The name of the element.
        :param element_data: Dictionary with element details.
        :param loop_key: Outer loop key (if applicable, e.g., 'videos').
        :param loop_values: List of values from the inner loop (e.g., content types, widgets).
        :param element_item: Optionally passed by wrap_with_element_items() decorator if builder requires extra loop

        :yield: A dictionary containing resolved element name and processed value.
        """

        string_values = defaultdict(set)

        for inner_item in ensure_list(loop_values):

            placeholders = self.resolver.build_placeholders(
                loop_key, inner_item, element_item
            )
            resolved = self.resolver.resolve({element_name: element_data}, placeholders)
            resolved_name, resolved_data = next(iter(resolved.items()), (None, None))
            value = self._process_single_element(resolved_data)

            if isinstance(value, dict):
                yield value
                break
            else:
                string_values[resolved_name].add(value if value else "false")
        else:
            yield {
                key: " | ".join(values - {"false"}) if values - {"false"} else "false"
                for key, values in string_values.items()
            }


class controlsBuilder(BaseBuilder):
    """
    Builds controls dynamically linked to skin settings for use in dynamic windows.
    """

    def _process_single_element(self, control_data):
        """ """
        ...


class expressionsBuilder(BaseBuilder):
    """
    Builds expressions defining visibility, inclusion, and logic for Kodi UI elements.
    """
    def process_elements(self, exp_name, exp_data):
        for exp_set in super().process_elements(exp_name, exp_data):
            yield self._apply_fallbacks(exp_set, exp_name, exp_data)

    @wrap_with_element_items
    def _resolve_element(
        self, exp_name, exp_data, loop_key, loop_values, element_item=None
    ):
        self.loop_key = loop_key
        yield from super()._resolve_element(
            exp_name, exp_data, loop_key, loop_values, element_item
        )

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

    def _apply_fallbacks(self, exp_set, exp_name, exp_data):
        fallback_key = next(
            (k for k in exp_data if k.startswith("fallback_for_")), ""
        )
        if not fallback_key:
            return exp_set

        placeholder = fallback_key.replace("fallback_for_","")
        fallback_data = exp_data[fallback_key]
        fallback_values = fallback_data.get("fallback_values", [])
        fallback_items = fallback_data.get("fallback_items", [])

        is_outer_loop = isinstance(
            self.loop_values, dict
        ) and placeholder in self.placeholders.get("key", [])

        if is_outer_loop:
            index = list(self.loop_values.keys()).index(self.loop_key)

        log(f"FUCK DEBUG self.placeholders {self.placeholders}", force=True)
        log(f"FUCK DEBUG self.loop_key {self.loop_key}", force=True)
        log(f"FUCK DEBUG self.loop_values {self.loop_values}", force=True)
        log(F'FUCK DEBUG exp_set {exp_set}', force=True)
        log(F'FUCK DEBUG exp_name {exp_name}', force=True)
        log(F'FUCK DEBUG exp_data {exp_data}', force=True)
        log(f"FUCK DEBUG placeholder {placeholder}", force=True)
        log(f"FUCK DEBUG fallback_values {fallback_values}", force=True)
        log(f"FUCK DEBUG fallback_items {fallback_items}", force=True)

        return exp_set

class skinsettingsBuilder(BaseBuilder):
    """
    Constructs simple map of allowed values for declared skin settings in a JSON file
    that can be used in dynamic settings windows to map settings to controls.
    """

    def _process_single_element(self, setting_data):
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

    @wrap_with_element_items
    def _resolve_element(
        self, var_name, var_data, loop_key, loop_values, element_item=None
    ):
        yield from super()._resolve_element(
            var_name, var_data, loop_key, loop_values, element_item
        )
    
    def _process_single_element(self, control_data):
        """ """
        ...
