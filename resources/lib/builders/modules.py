# author: realcopacetic

import json
import re
from collections import defaultdict
from itertools import product
from urllib.parse import quote

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared.utilities import expand_index, log

PLACEHOLDER_PATTERN = re.compile(r"{(.*?)}")


class BaseBuilder:
    """
    Base class for all builders that handles loop expansion and substitution logic.
    Used by all specialized builder types to generate template values.
    """

    def __init__(self, loop_values, placeholders, metadata):
        """
        Initializes builder with placeholders, loop values, and dynamic key.

        :param loop_values: List or dict of content types or keys to loop over.
        :param placeholders: Dictionary of placeholder names for formatting.
        :param placeholders: Dictionary of metatada for injection into xml elements
        """
        self.loop_values, self.placeholders, self.metadata = (
            loop_values,
            placeholders,
            metadata,
        )
        self.rules = RuleEngine()
        self.group_map = {}

    def process_elements(self, element_name, element_data):
        """
        Processes a template element by generating and expanding substitutions.

        :param element_name: The name of the expression/template.
        :param element_data: Data dict containing rules and item values.
        :returns: Generator yielding {name: value} dicts.
        """
        items = element_data.get("items") or expand_index(element_data.get("index"))
        dynamic_key_mapping = {"items": "item", "index": "index"}
        dynamic_key = next(
            (
                dynamic_key_mapping[key]
                for key in dynamic_key_mapping
                if key in element_data
            ),
            None,
        )
        substitutions = self.generate_substitutions(items, dynamic_key)
        yield from (
            {k: v}
            for k, v in self.group_and_expand(
                element_name, element_data, substitutions
            ).items()
        )

    def generate_substitutions(self, items, dynamic_key):
        """
        Generates substitution dicts based on loop structure and items.

        :param items: List of items to loop over.
        :param dynamic_key: Optional substitution key used in json/xml templates (either "item" or "index")
        :returns: List of substitution dictionaries.
        """
        key_name = self.placeholders.get("key")
        value_name = self.placeholders.get("value")

        if isinstance(self.loop_values, dict) and items:
            return [
                self._inject_metadata(
                    {
                        key_name: outer_key,
                        value_name: inner_value,
                        dynamic_key: item,
                    },
                    outer_key,
                    inner_value,
                )
                for outer_key, inner_values in self.loop_values.items()
                for inner_value, item in product(inner_values, items)
            ]

        elif isinstance(self.loop_values, dict) and not items:
            return [
                self._inject_metadata(
                    {
                        key_name: outer_key,
                        value_name: inner_value,
                    },
                    outer_key,
                    inner_value,
                )
                for outer_key, inner_values in self.loop_values.items()
                for inner_value in inner_values
            ]

        elif isinstance(self.loop_values, list) and items:
            return [
                self._inject_metadata(
                    {
                        key_name: loop_value,
                        dynamic_key: item,
                    },
                    loop_value,
                )
                for loop_value, item in product(self.loop_values, items)
            ]

        elif isinstance(self.loop_values, list) and not items:
            return [
                self._inject_metadata({key_name: loop_value}, loop_value)
                for loop_value in self.loop_values
            ]

        elif not self.loop_values and items:
            return [
                {
                    dynamic_key: item,
                }
                for item in items
            ]

        raise ValueError(
            "Missing loop value items and items/index in json/xml templates"
        )

    def substitute(self, object, substitutions):
        """
        Formats an object using the provided substitution dictionary.

        :param object: Template string with placeholders.
        :param substitutions: Dict of key-value substitutions.
        :returns: Fully formatted string.
        """
        if isinstance(object, str):
            if not substitutions or ("{" not in object):
                return object
            return PLACEHOLDER_PATTERN.sub(
                lambda match: substitutions.get(match.group(1), ""),
                object,
            )

        elif isinstance(object, list):
            return [self.substitute(item, substitutions) for item in object]

        elif isinstance(object, dict):
            substituted_dict = {
                key: self.substitute(value, substitutions)
                for key, value in object.items()
            }
            return {k: v for k, v in substituted_dict.items() if v not in ("", {}, [], None)}

        else:
            return object

    def _inject_metadata(self, substitutions, *keys):
        """Merge substitutions with metadata if metadata for any key exists."""
        combined_metadata = {}
        for key in keys:
            metadata = self.metadata.get(key, {})
            combined_metadata.update(metadata)
        return {**substitutions, **combined_metadata}


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

        # Dynamic controls with inner recursive expansion
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
        # Static controls with standard expansion
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


class includesBuilder(BaseBuilder):
    """
    Expands Kodi XML 'include' templates by substituting placeholders and encoding XSP metadata.
    Handles recursive multi-level expansions for dynamic XML generation.
    """

    def __init__(self, loop_values, placeholders, metadata):
        super().__init__(loop_values, placeholders, metadata)
        self._prepare_xsp_urls()

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups substitutions by expanded template names and expands values.

        :param template_name: Template string possibly containing placeholders.
        :param data: Dictionary representing XML structure.
        :param substitutions: List of substitution dictionaries.
        """
        has_placeholder = any(
            f"{{{key}}}" in template_name for sub in substitutions for key in sub
        )

        grouped = defaultdict(list)
        if has_placeholder:
            for sub in substitutions:
                key = template_name.format(**sub)
                grouped[key].append(sub)
                self.group_map[key] = sub
        else:
            grouped[template_name] = substitutions

        return {
            key: self.resolve_values(subs, data["include"])
            for key, subs in grouped.items()
        }

    def resolve_values(self, substitutions, include_element):
        """
        Resolves values recursively within the include element with substitutions.

        :param substitutions: List of substitution dictionaries.
        :param include_element: Dictionary representing the include XML structure.
        """
        return {"include": self.recursive_expand(include_element, substitutions)}

    def recursive_expand(self, data, substitutions):
        """
        Recursively expands placeholders within dictionaries and lists, explicitly
        removing elements and attributes with empty "@value" or "#text" after substitution.

        :param data: Data structure (dict, list, or string) with potential placeholders.
        :param substitutions: List of substitution dictionaries.
        """
        if isinstance(data, dict):
            expanded_dict = {
                key: self.recursive_expand(value, substitutions)
                for key, value in data.items()
            }
            if ("@value" in expanded_dict and expanded_dict["@value"] == "") or (
                "#text" in expanded_dict and expanded_dict["#text"] == ""
            ):
                return {}
            return {
                k: v for k, v in expanded_dict.items() if v not in ("", {}, [], None)
            }

        elif isinstance(data, list):
            expanded_list = []
            for item in data:
                expand_multiple = (
                    isinstance(item, dict)
                    and "@content" in item
                    and any(
                        f"{{{p}}}" in item["@content"]
                        for sub in substitutions
                        for p in sub
                    )
                )
                sub_list = substitutions if expand_multiple else [substitutions[0]]
                for sub in sub_list:
                    expanded_item = self.recursive_expand(item, [sub])
                    if expanded_item not in ({}, [], "", None):
                        expanded_list.append(expanded_item)

            return expanded_list

        elif isinstance(data, str):
            return self.substitute(data, substitutions[0])

        return data

    def _prepare_xsp_urls(self):
        """
        Encodes XSP dictionaries in metadata into URL-encoded strings.
        Removes encoded quotes (%22) around $ESCINFO[] references.
        """
        escinfo_pattern = re.compile(r"%22(\$ESCINFO\[.*?\])%22")

        for meta in self.metadata.values():
            if "xsp" in meta:
                xsp_json = quote(json.dumps(meta["xsp"]))
                xsp_json = escinfo_pattern.sub(r"\1", xsp_json)
                meta["xsp"] = f"?xsp={xsp_json}"


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

        resolved = {
            key: self.resolve_values(subs, data) for key, subs in grouped.items()
        }

        return self._apply_defaults(resolved, data)

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

    def _apply_defaults(self, resolved, setting_data):
        """
        Resolves default values per window or content type, similar to fallbacks.

        :param resolved: Dict of resolved skinsettings.
        :param setting_data: The full skinsetting definition including defaults.
        :returns: Updated resolved settings dict with defaults applied.
        """
        default_key = next(
            (k for k in setting_data if k.startswith("defaults_for_")), None
        )
        if not default_key:
            return resolved

        default_field = default_key.replace("defaults_for_", "").strip("{}")
        defaults_values = setting_data[default_key].get("defaults_values", [])

        settings_by_group = defaultdict(list)
        for setting_name in resolved:
            sub = self.group_map.get(setting_name, {})
            group = sub.get(default_field)
            if group:
                settings_by_group[group].append(setting_name)

        for i, (group_key, setting_list) in enumerate(settings_by_group.items()):
            default_value = defaults_values[min(i, len(defaults_values) - 1)]
            for setting_name in setting_list:
                resolved[setting_name]["default"] = default_value

        return resolved


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
