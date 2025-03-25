# author: realcopacetic

import re
from resources.lib.shared.utilities import condition


class RuleEngine:
    """
    Evaluates conditional expressions using predefined operators or Kodi conditions.
    Supports caching, inversion, and dynamic expression parsing.
    """

    # Regex to match conditions in the form: "[not] EvaluatorKeyword(param1, param2)"
    CONDITION_PATTERN = re.compile(r"^(not\s+)?(\w+)\(\s*([^,]+)\s*,\s*([^)]+)\s*\)$")

    CONDITION_MAP = {
        "in": lambda subj, vals: subj
        in [x.strip() for x in vals.strip("[]").split(",")],
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
        """Initializes the RuleEngine with an empty condition cache."""
        self.condition_cache = {}

    def evaluate(self, condition):
        """
        Evaluates a condition string, using cached results if available.

        :param condition: The condition string to evaluate.
        :returns: Boolean result of the evaluated condition.
        """
        if condition in self.condition_cache:
            return self.condition_cache[condition]

        result = self._evaluate_condition(condition)
        self.condition_cache[condition] = result
        return result

    def _evaluate_condition(self, condition_str):
        """
        Parses and evaluates a condition string using regex and evaluators.

        :param condition_str: The full condition string to evaluate.
        :returns: True if the condition evaluates successfully, else False.
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
        Builds a Kodi boolean inversion expression from a dictionary of values.

        :param values_dict: Dictionary of expression values to invert.
        :returns: A Kodi-formatted inversion expression string.
        """
        values = [v for v in values_dict.values() if v and v != "false" and v != "true"]

        return "true" if not values else f"![{ ' | '.join(values) }]"
