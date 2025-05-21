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

    def __init__(self, mapping_name, mapping_values, runtime_manager=None):
        """
        Initializes builder with placeholders, loop values, and dynamic key.

        :param mapping: Looping values, placeholders and metadata for expansion
        :param runtime_manager: Instance of manager class for handling runtime configs
        """
        self.mapping_name = mapping_name
        self.mapping_values = mapping_values
        self.loop_values = mapping_values.get("items")
        self.placeholders = mapping_values.get("placeholders", {})
        self.metadata = mapping_values.get("metadata", {})
        self.runtime_manager = runtime_manager
        self.rules = RuleEngine()
        self.group_map = {}

    def process_elements(self, element_name, element_data):
        """
        Processes a template element by generating and expanding substitutions.

        :param element_name: The name of the expression/template.
        :param element_data: Data dict containing rules and item values.
        :returns: Generator yielding {name: value} dicts.
        """
        expansion_type = element_data.get("expansion", "mapping")

        if (
            expansion_type == "runtimejson"
            and self.runtime_manager is not None
            and (
                runtime_items := self.runtime_manager.runtime_state.get(
                    self.mapping_name
                )
            )
        ):
            index_start = int(element_data.get("index", {}).get("@start", 1))
            substitutions = self.generate_runtimejson_substitutions(
                runtime_items, index_start
            )
        else:
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

    def generate_runtimejson_substitutions(self, runtime_items, index_start):
        """
        Generates substitution dictionaries for runtimejson expansion,
        injecting index, mapping placeholder, and all runtime values.

        :param runtime_items: List of runtime state items for this mapping.
        :param index_start: Starting index value (default 1).
        :returns: List of substitution dictionaries for template expansion.
        """
        key_placeholder = self.placeholders.get("key")
        return [
            self._inject_metadata(
                {
                    key_placeholder: item["mapping_item"],
                    "index": str(index_start + index),
                    **{k: v for k, v in item.items() if k != "mapping_item"},
                },
                item["mapping_item"],
            )
            for index, item in enumerate(runtime_items)
        ]

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
            return {
                k: v for k, v in substituted_dict.items() if v not in ("", {}, [], None)
            }

        else:
            return object

    def _inject_metadata(self, substitutions, *keys):
        """Merge substitutions with metadata if metadata for any key exists."""
        combined_metadata = {}
        for key in keys:
            metadata = self.metadata.get(key, {})
            combined_metadata.update(metadata)
        return {**substitutions, **combined_metadata}


class configsBuilder(BaseBuilder):
    """
    Builder that resolves UI configs based on exclusion/inclusion rules.
    """

    def group_and_expand(self, template_name, data, substitutions):
        """
        Groups and evaluates configs options based on filtering logic.

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
        defaults = {
            "items": [],
            "storage": "runtimejson",
            "filter_mode": "exclude",
            "rules": [],
        }
        resolved_data = {**defaults, **data}

        excluded = {
            value
            for sub in subs
            for rule in resolved_data["rules"]
            if self.rules.evaluate(rule["condition"].format(**sub))
            for value in rule.get("value", [])
        }
        resolved_data["items"] = [
            item
            for item in resolved_data["items"]
            if (item not in excluded) == (resolved_data["filter_mode"] == "exclude")
        ]
        prefixes_to_remove = ("defaults_per_", "filter_mode", "rules")

        return {
            key: value
            for key, value in resolved_data.items()
            if not key.startswith(prefixes_to_remove)
        }

    def _apply_defaults(self, resolved, setting_data):
        """
        Resolves default values per loop value placeholder, similar to fallbacks.
        Default will only be applied if it is an allowed config value.
        If only one config value is allowed, this will overwrite any default.

        :param resolved: Dict of resolved configs.
        :param setting_data: The full config definition including defaults.
        :returns: Updated resolved settings dict with defaults applied.
        """
        default_entry = next(
            ((k, v) for k, v in setting_data.items() if k.startswith("defaults_per_")),
            (None, None),
        )

        default_key, default_values = default_entry
        if not default_key:
            return resolved

        default_field = default_key[len("defaults_per_") :].strip("{}")

        all_settings_by_group = defaultdict(list)
        for setting_name in resolved:
            sub = self.group_map.get(setting_name, {})
            if default_field in sub:
                all_settings_by_group[sub[default_field]].append(setting_name)

        for i, (group_key, setting_list) in enumerate(all_settings_by_group.items()):
            default_value = default_values[min(i, len(default_values) - 1)]

            if not setting_list:
                continue

            for setting_name in setting_list:
                allowed_items = resolved[setting_name]["items"]
                if (
                    default_value not in allowed_items
                ):  # default_value prohibited, safe fallback to first allowed item
                    fallback_default = allowed_items[0]
                    resolved[setting_name]["default"] = fallback_default

                    log(
                        f"{self.__class__.__name__}: [Default override] {setting_name} default '{default_value}' invalid; using '{fallback_default}' instead (group: {group_key})"
                    )
                else:  # default_value allowed
                    resolved[setting_name]["default"] = default_value
                    log(
                        f"{self.__class__.__name__}: [Default applied] {setting_name} default = {default_value} (group: {group_key})",
                    )

        return resolved


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

            linked_config = data["dynamic_linking"].get("linked_config")
            schema = self.mapping_values.get("user_defined_schema", {})
            configs = schema.get("configs", {})
            field_name = next(
                (
                    fname
                    for fname, template in configs.items()
                    if template == linked_config
                ),
                None,
            )

            return {
                template_name: {
                    "mapping": self.mapping_name,
                    **({"field": field_name} if field_name else {}),
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
            "mapping": self.mapping_name,
            **{
                field: self.substitute(value, sub)
                for field, value in data.items()
                if isinstance(value, str)
            },
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
                condition = rule.get("condition")

                if condition:
                    formatted_condition = condition.format(**sub)
                    if not self.rules.evaluate(formatted_condition):
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
        fallback_entry = next(
            ((k, v) for k, v in expr_data.items() if k.startswith("fallback_per_")),
            (None, None),
        )

        fallback_key, fallback_dict = fallback_entry
        if not fallback_key:
            return resolved

        fallback_field = fallback_key[len("fallback_per_") :].strip("{}")
        fallback_values = fallback_dict.get("values", [])
        fallback_items = fallback_dict.get("target_items", fallback_values)

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

    def __init__(self, mapping_name, mapping_values, runtime_manager=None):
        super().__init__(mapping_name, mapping_values, runtime_manager)
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

    def contains_placeholder(self, data, substitutions):
        """
        Recursively checks if data contains any placeholders from substitutions.
        """
        if isinstance(data, dict):
            return any(
                self.contains_placeholder(value, substitutions)
                for value in data.values()
            )
        elif isinstance(data, list):
            return any(self.contains_placeholder(item, substitutions) for item in data)
        elif isinstance(data, str):
            return any(f"{{{p}}}" in data for sub in substitutions for p in sub)
        return False

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
                k: v
                for k, v in expanded_dict.items()
                if v not in ({}, [], "", None) or k == "nested"
            }

        elif isinstance(data, list):
            expanded_list = []
            for item in data:
                expand_multiple = self.contains_placeholder(item, substitutions)
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
