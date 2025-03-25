# author: realcopacetic

from collections import defaultdict
from itertools import product

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import log

def expand_index(index_obj):
    try:
        start = int(index_obj["start"])
        end = int(index_obj["end"]) + 1
        step = int(index_obj.get("step", 1))
        return [str(i) for i in range(start, end, step)]
    except (KeyError, TypeError, ValueError):
        return []

class BaseBuilder:
    def __init__(self, loop_values, placeholders, dynamic_key):
        self.loop_values = loop_values
        self.placeholders = placeholders
        self.dynamic_key = dynamic_key
        self.rules = RuleEngine()
        self.group_map = {}

    def process_elements(self, element_name, element_data):
        """
        Processes a single template element by generating all substitutions,
        expanding rules, and returning final results.
        """
        items = element_data.get("items") or expand_index(element_data.get("index")) or []
        substitutions = self.generate_substitutions(items)

        yield from (
            {k: v}
            for k, v in self.group_and_expand(
                element_name, element_data, substitutions
            ).items()
        )

    def generate_substitutions(self, items):
        """
        Generates all valid placeholder-to-value substitution dictionaries for a single element.
        Raises an error if required placeholder keys are missing.
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
        return string.format(**substitutions)


class controlsBuilder(BaseBuilder):
    def resolve_values(self, subs, rules):
        raise NotImplementedError(
            "controlsBuilder does not implement resolve_values() yet."
        )


class expressionsBuilder(BaseBuilder):
    """
    Builder that processes expression definitions by resolving template placeholders
    and evaluating rule-based logic to produce final expressions.
    """

    def process_elements(self, element_name, element_data):
        resolved = {}
        for d in super().process_elements(element_name, element_data):
            resolved.update(d)

        yield self._apply_fallbacks(resolved, element_data)

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups substitutions by formatted template name and applies resolve_values()
        to produce the final value for each group.
        Returns a dict of {resolved_template_name: expression_value}.
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
        Evaluates all rules for a group of substitutions, returning the final values
        according to rule priority and type.
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
                    f"[Fallback skipped] No match for fallback_item '{fallback_item}' in group '{group_key}'",
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
                f"[Fallback applied] {target_expr} = {resolved[target_expr]} (group: {group_key}, others: {list(others.keys())})",
            )

        return resolved


class skinsettingsBuilder(BaseBuilder):
    def group_and_expand(self, template_name, data, substitutions):
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub

        return {key: self.resolve_values(subs, data) for key, subs in grouped.items()}

    def resolve_values(self, subs, data):
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
    def group_and_expand(self, template_name, data, substitutions):
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
        values = data.get("values", [])
        index_range = expand_index(data.get("index"))

        if index_range is None:
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
