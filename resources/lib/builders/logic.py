# author: realcopacetic

import re
from resources.lib.shared.utilities import condition, log


class RuleEngine:
    """Class-based evaluator for condition strings, supporting dynamic evaluations."""

    # Regex to match conditions in the form: "[not] EvaluatorKeyword(param1, param2)"
    CONDITION_PATTERN = re.compile(r"^(not\s+)?(\w+)\(\s*([^,]+)\s*,\s*([^)]+)\s*\)$")

    CONDITION_MAP = {
        "in": lambda subj, vals: subj in [x.strip() for x in vals.strip("[]").split(",")],
        "equals": lambda subj, val: subj == val,
        "not_equals": lambda subj, val: subj != val,
        "startswith": lambda subj, prefix: subj.startswith(prefix),
        "endswith": lambda subj, suffix: subj.endswith(suffix),
        "contains": lambda subj, substring: substring in subj,
        "greaterthan": lambda subj, val: float(subj) > float(val),
        "lessthan": lambda subj, val: float(subj) < float(val),
        "greaterorequal": lambda subj, val: float(subj) >= float(val),
        "lessorequal": lambda subj, val: float(subj) <= float(val),
    }

    def __init__(self):
        self.condition_cach = {}

    def evaluate(self, condition):
        if condition in self.condition_cach:
            return self.condition_cach[condition]

        result = self._evaluate_condition(condition)
        self.condition_cach[condition] = result
        return result

    def _evaluate_condition(self, condition_str):
        """
        Evaluates a condition string and returns True or False. Parses condition using regex
        and looks up appropriate evaluator CONDIITON_MAP.
        """
        # Check first for Kodi native expressions marked "xml(expression)"
        if condition_str.lower().startswith("xml("):
            inner = condition_str[4:-1].strip()
            return condition(inner)

        # Use regex matching for all other conditions.
        if match := self.CONDITION_PATTERN.match(condition_str):
            is_negative = match.group(1) is not None
            evaluator_keyword = match.group(2).lower()
            item1 = match.group(3).strip()
            item2 = match.group(4).strip()

            evaluator_func = self.CONDITION_MAP.get(evaluator_keyword)

            if evaluator_func:
                result = evaluator_func(item1, item2)
                return not result if is_negative else result

        return False

    def invert(self, values_dict):
        """
        Inverts the given values.

        :param values_dict: A dictionary mapping keys to their values.
        :return: A properly formatted inverted expression.
        """
        values = [v for v in values_dict.values() if v and v != "false" and v != "true"]

        if not values:
            return "true"

        return f"![{ ' | '.join(values) }]"


class PlaceholderResolver:
    """Resolves placeholders efficiently by separating placeholder creation and substitution."""

    def __init__(self, loop_values=None, placeholders=None, dynamic_key=None):
        self.loop_values = loop_values
        self.base_placeholders = placeholders
        self.dynamic_key = dynamic_key
        self.expanded_placeholders = self._expand()

    def _expand(self):
        

    def build_placeholders(self, *values):
        """
        Dynamically maps placeholders stored in self.mapping to the values passed in.

        :param values: Ordered values to match with the keys in self.mapping.
        :return: A dictionary where the placeholders are correctly assigned their values.
        """
        valid_values = [v for v in values if v is not None]

        return {
            placeholder: value
            for (_, placeholder), value in zip(self.mapping.items(), valid_values)
        }

    def resolve(self, data, placeholders):
        """
        Recursively resolves placeholders in strings, lists, and dictionaries.
        Also replaces placeholders in dictionary keys.

        :param data: The text, list, or dictionary containing placeholders.
        :param placeholders: Dictionary of placeholder mappings.
        :return: Data with placeholders replaced.
        """
        if isinstance(data, str):
            for key, value in placeholders.items():
                data = data.replace(key, value)
            return data

        # Process each list item recursively
        elif isinstance(data, list):
            return [self.resolve(item, placeholders) for item in data]

        # Process both keys and values recursively
        elif isinstance(data, dict):
            return {
                self.resolve(k, placeholders): self.resolve(v, placeholders)
                for k, v in data.items()
            }

        # Return unchanged if not string, list, or dict
        return data
