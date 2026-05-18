# author: realcopacetic

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import quote

from resources.lib.builders.logic import RuleEngine
from resources.lib.builders.substitution import enumerate_mapping_subs, inject_metadata
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import evaluate_expression, expand_index

PLACEHOLDER_PATTERN = re.compile(r"{(.*?)}")


class BaseBuilder:
    """
    Base class for all builders that handles loop expansion and substitution logic.
    Used by all specialized builder types to generate template values.
    """

    def __init__(self, mapping_name, mapping_values, runtime_manager=None):
        """
        Initialise the builder with the mapping it operates on.

        :param mapping_name: Name of the mapping driving this builder.
        :param mapping_values: Mapping definition (items, placeholders, metadata).
        :param runtime_manager: Runtime state manager for dynamic-mode lookups.
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
        :return: Generator yielding {name: value} dicts.
        """
        mode = element_data.get("mode", "static")
        template_items = element_data.get("items")
        template_index_data = element_data.get("index")

        if mode == "dynamic":
            runtime_items = (
                self.runtime_manager.runtime_state.get(self.mapping_name) or []
            )
            if not runtime_items:
                log.debug(
                    f"{self.__class__.__name__}: No runtime state for "
                    f"'{self.mapping_name}' — dynamic template '{element_name}' "
                    f"expands with no per-entry substitutions."
                )
            index_list = expand_index(template_index_data)
            index_start = int(index_list[0]) if index_list else 1
            substitutions = self.generate_runtimejson_substitutions(
                runtime_items, index_start
            )
        else:
            substitutions = enumerate_mapping_subs(self.mapping_values)
            if template_index_data:
                substitutions = [
                    {**sub, "index": str(idx)}
                    for sub in substitutions
                    for idx in expand_index(template_index_data)
                ]

        if template_items:
            substitutions = [
                {**sub, "item": str(item)}
                for sub in substitutions
                for item in template_items
            ]

        if filter_expr := element_data.get("filter"):
            substitutions = [
                sub
                for sub in substitutions
                if self.rules.evaluate(self.substitute(filter_expr, sub))
            ]

        self._add_loop_position_flags(substitutions)

        yield from (
            {k: v}
            for k, v in self.group_and_expand(
                element_name, element_data, substitutions
            ).items()
        )

    def generate_runtimejson_substitutions(self, runtime_items, index_start):
        """
        Each runtime entry contributes its scalar (string) fields layered over
        per-item metadata; non-string runtime values (e.g. xsp dicts) come from metadata only.

        :param runtime_items: List of runtime state items for this mapping.
        :param index_start: Starting index value (default 1).
        :return: List of substitution dictionaries for template expansion.
        """
        key_placeholder = self.placeholders.get("key")
        return [
            inject_metadata(
                self.metadata,
                {
                    key_placeholder: item["mapping_item"],
                    "index": str(index_start + index),
                    **{
                        k: v
                        for k, v in item.items()
                        if k != "mapping_item" and isinstance(v, str)
                    },
                },
                item["mapping_item"],
            )
            for index, item in enumerate(runtime_items)
        ]

    def _group_substitutions(self, template_name, substitutions):
        """
        Group substitutions by their expanded template name.

        When every substitution has been filtered out, a template whose
        name contains no placeholder still yields one empty group — so a
        constant-named element is emitted even with nothing to expand.

        :param template_name: Template name, possibly with placeholders.
        :param substitutions: List of substitution dicts (may be empty).
        :return: Mapping of expanded name → list of substitutions.
        """
        grouped = defaultdict(list)
        for sub in substitutions:
            key = template_name.format(**sub)
            grouped[key].append(sub)
            self.group_map[key] = sub
        if not grouped and "{" not in template_name:
            grouped[template_name] = []
        return grouped

    def _resolve_placeholder(
        self, match: re.Match, substitutions: dict[str, str]
    ) -> str:
        """
        Resolve a single placeholder match against the substitution dict.
        Falls back to numeric expression evaluation for arithmetic and min/max.

        :param match: Regex match object from PLACEHOLDER_PATTERN.
        :param substitutions: Dict of key-value substitutions.
        :return: Substituted value, or empty string if placeholder is unknown.
        """
        key = match.group(1)

        if key in substitutions:
            return substitutions[key]

        result = evaluate_expression(key, substitutions)
        if result is not None:
            return result

        return ""

    def substitute(self, template: str, substitutions: dict[str, str]) -> str:
        """
        Substitute placeholders in a template string against a substitution dict.

        :param template: Template string with placeholders.
        :param substitutions: Dict of key-value substitutions.
        :return: Formatted string.
        """
        if not substitutions or ("{" not in template):
            return template

        return PLACEHOLDER_PATTERN.sub(
            lambda match: self._resolve_placeholder(match, substitutions),
            template,
        )

    def _resolve_placeholder_strict(
        self, match: re.Match, tokens: dict[str, str]
    ) -> str:
        """
        Like _resolve_placeholder but leaves unknown placeholders intact.
        Used for pre-pass substitution of template-level tokens before the
        per-item expansion runs.

        :param match: Regex match object from PLACEHOLDER_PATTERN.
        :param tokens: Dict of template-level token values.
        :return: Substituted value; original ``{placeholder}`` if unresolved.
        """
        key = match.group(1)
        if key in tokens:
            return tokens[key]
        result = evaluate_expression(key, tokens)
        if result is not None:
            return result
        return match.group(0)

    def substitute_strict(self, template, tokens):
        """
        Walk a template tree and substitute only placeholders resolvable from
        ``tokens``, leaving all others intact. Does not prune empty values —
        pruning happens in the downstream per-item expansion.

        :param template: Template string, list, or dict to walk.
        :param tokens: Dict of template-level token values.
        :return: Tree with template-level placeholders resolved.
        """
        if isinstance(template, str):
            if "{" not in template:
                return template
            return PLACEHOLDER_PATTERN.sub(
                lambda m: self._resolve_placeholder_strict(m, tokens), template
            )
        if isinstance(template, list):
            return [self.substitute_strict(item, tokens) for item in template]
        if isinstance(template, dict):
            return {k: self.substitute_strict(v, tokens) for k, v in template.items()}
        return template

    @staticmethod
    def _add_loop_position_flags(substitutions: list[dict[str, str]]) -> None:
        """
        Inject loop-position metadata into every substitution dict in place.
        Adds ``count`` (total substitutions, identical across all entries),
        ``is_first`` ('true' on the first entry only), and ``is_last``
        ('true' on the last entry only). Strings are used so the values can
        be substituted directly into Kodi boolean conditions.

        :param substitutions: List of substitution dictionaries to annotate.
        """
        total = len(substitutions)
        last = total - 1
        count_str = str(total)
        for i, sub in enumerate(substitutions):
            sub["count"] = count_str
            sub["is_first"] = "true" if i == 0 else "false"
            sub["is_last"] = "true" if i == last else "false"


class ExpressionsBuilder(BaseBuilder):
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
        :return: Generator yielding final expression dict.
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
        :return: Dictionary of {expression_key: expression_value}.
        """
        grouped = self._group_substitutions(template_name, substitutions)
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
        :return: List of expression values (or "false" fallback).
        """
        resolved = []
        rules = data.get("rules", [])

        for sub in subs:
            for rule in rules:
                condition = rule.get("condition")

                if condition:
                    formatted_condition = self.substitute(condition, sub)
                    if not self.rules.evaluate(formatted_condition):
                        continue

                value = self.substitute(rule["value"], sub)

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
        :return: Updated resolved expression dict with fallbacks applied.
        """
        fallbacks = expr_data.get("fallbacks")
        fallback_key = expr_data.get("fallback_key")
        if not fallbacks or not fallback_key:
            return resolved

        all_exprs_by_group = defaultdict(list)
        for expr_name in resolved:
            sub = self.group_map.get(expr_name, {})
            if fallback_key in sub:
                all_exprs_by_group[sub[fallback_key]].append(expr_name)

        for group_key, expr_list in all_exprs_by_group.items():
            fallback_entry = fallbacks.get(group_key) or fallbacks.get("*")
            if not fallback_entry:
                continue

            fallback_item = fallback_entry.get("target_item")
            fallback_value = fallback_entry.get("value")
            if not fallback_item or fallback_value is None:
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
                log.verbose(
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

            log.verbose(
                f"{self.__class__.__name__}: [Fallback applied] {target_expr} = {resolved[target_expr]} (group: {group_key}, others: {list(others.keys())})",
            )

        return resolved


class IncludesBuilder(BaseBuilder):
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
        grouped = self._group_substitutions(template_name, substitutions)
        return {
            key: (
                self.resolve_values(subs, data["include"])
                if subs
                else {"include": self._empty_include_shell(data["include"])}
            )
            for key, subs in grouped.items()
        }

    def resolve_values(self, substitutions, include_element):
        """
        Resolves values recursively within the include element with substitutions.
        Template-level tokens (currently 'count') are pre-substituted across the
        whole tree before per-item expansion, so they don't trigger multiplication
        in contains_placeholder.

        :param substitutions: List of substitution dictionaries.
        :param include_element: Dictionary representing the include XML structure.
        """
        template_tokens = {"count": str(len(substitutions))}
        pre_resolved = self.substitute_strict(include_element, template_tokens)
        return {"include": self.recursive_expand(pre_resolved, substitutions)}

    def contains_placeholder(self, data, substitutions):
        """
        Recursively check whether data contains any placeholder that references
        a substitution key, including arithmetic placeholders such as
        ``{index1}``, ``{index-count-1}`` or ``{min(count*100, 800)}``.

        :param data: Data structure (dict, list, or string) to inspect.
        :param substitutions: List of substitution dictionaries.
        :return: ``True`` if any ``{...}`` token in ``data`` references a
            substitution key.
        """
        if isinstance(data, dict):
            return any(
                self.contains_placeholder(value, substitutions)
                for value in data.values()
            )
        elif isinstance(data, list):
            return any(self.contains_placeholder(item, substitutions) for item in data)
        elif isinstance(data, str):
            if "{" not in data:
                return False
            sub_keys = {key for sub in substitutions for key in sub}
            for match in PLACEHOLDER_PATTERN.finditer(data):
                tokens = re.findall(r"\b\w+\b", match.group(1))
                if any(token in sub_keys for token in tokens):
                    return True
            return False
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

    @staticmethod
    def _empty_include_shell(include_element: dict) -> dict:
        """
        Reduce an include element to its attributes only — a named include
        with an empty body. Emitted when every loop value was filtered out,
        so an include hardcoded-referenced in skin XML still resolves.

        :param include_element: Include element dict from the template.
        :return: Dict with only the element's ``@``-prefixed attribute keys.
        """
        shell = {k: v for k, v in include_element.items() if k.startswith("@")}
        shell["description"] = "placeholder"
        return shell


class VariablesBuilder(BaseBuilder):
    """
    Builder that generates Kodi-style variable definitions with condition/value pairs.
    Supports ordinary shape (``{values: [...]}`` — one variable per template) and cluster
    shape (``{outputs, rows}`` — multiple variables sharing a single row cascade).
    """

    def group_and_expand(self, template_name, data, substitutions):
        """
        Cluster templates emit one variable per declared output sharing a row
        cascade; ordinary templates emit one variable per template (optionally indexed).

        :param template_name: Template for variable name.
        :param data: Rule and value definitions for the variable.
        :param substitutions: List of substitution dicts.
        :return: Dictionary of variable name → value list.
        """
        if "outputs" in data:
            return self._expand_cluster(data, substitutions)

        grouped = self._group_substitutions(template_name, substitutions)
        return {
            variable["name"]: variable["values"]
            for subs in grouped.values()
            for variable in self.resolve_values(template_name, subs, data)
        }

    def _expand_cluster(
        self,
        data: dict[str, Any],
        substitutions: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, str]]]:
        """
        Expand a cluster into one variable per declared output. Subs are
        grouped by the variable name each produces, then expanded with the
        same block rules as ordinary templates.

        :param data: Cluster template dict with ``outputs`` and ``rows``.
        :param substitutions: Substitution dicts from the loop expansion.
        :return: Mapping of variable name to list of value dicts.
        """
        outputs = data.get("outputs", {})
        blocks = self._as_blocks(data.get("rows", []))
        result: dict[str, list[dict[str, str]]] = {}

        for output_key, name_template in outputs.items():
            projected = self._project_cluster_output(blocks, output_key)

            # Constant-named outputs still emit with zero subs; a placeholder
            # name with no subs has nothing to resolve a name from.
            if substitutions:
                subs = substitutions
            elif "{" not in name_template:
                subs = [{}]
            else:
                continue

            grouped = defaultdict(list)
            for sub in subs:
                grouped[self.substitute(name_template, sub)].append(sub)

            for name, group_subs in grouped.items():
                result[name] = self._ensure_nonempty(
                    self._expand_blocks(projected, group_subs)
                )

        return result

    def _project_cluster_output(
        self,
        blocks: list[list[dict[str, str]]],
        output_key: str,
    ) -> list[list[dict[str, str]]]:
        """
        Project cluster blocks onto one output. Rows not contributing to it
        (sparse rows) and blocks empty for it are dropped.

        :param blocks: Normalised cluster row blocks.
        :param output_key: Output name to project onto.
        :return: List of {condition, value} pair blocks for this output.
        """
        projected = []
        for block in blocks:
            pairs = [
                {"condition": row.get("condition", ""), "value": row[output_key]}
                for row in block
                if output_key in row
            ]
            if pairs:
                projected.append(pairs)
        return projected

    def resolve_values(
        self,
        template_name: str,
        subs: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build one variable from a template and its substitution group.

        :param template_name: Name pattern of variable.
        :param subs: Substitution group for this variable (may be empty).
        :param data: Variable definition including values.
        :return: Single-item list with the resolved variable dict.
        """
        name = self.substitute(template_name, subs[0] if subs else {})
        blocks = self._as_blocks(data.get("values", []))
        return [
            {
                "name": name,
                "values": self._ensure_nonempty(self._expand_blocks(blocks, subs)),
            }
        ]

    @staticmethod
    def _as_blocks(values: list) -> list[list[dict[str, str]]]:
        """
        Normalise a values/rows list into blocks. A bare dict becomes a
        one-row block; a list is an explicit multi-row block.

        :param values: Raw values (ordinary) or rows (cluster) list.
        :return: List of blocks, each a list of row dicts.
        """
        return [v if isinstance(v, list) else [v] for v in values]

    @staticmethod
    def _ensure_nonempty(values: list) -> list:
        """
        Guarantee at least one value row. A ``<variable>`` with no
        ``<value>`` children is undefined in Kodi (``$VAR[...] is not
        defined``); a single empty ``<value/>`` keeps the variable defined
        and resolving to an empty string.

        :param values: Resolved list of value dicts (may be empty).
        :return: The list, or a single empty value row if it was empty.
        """
        return values or [{"value": ""}]

    @staticmethod
    def _block_has_placeholder(block: list[dict[str, str]]) -> bool:
        """
        Report whether a block varies per substitution.

        :param block: A list of {condition, value} pair dicts.
        :return: True if any field of any row contains a placeholder.
        """
        return any(
            isinstance(field, str) and "{" in field
            for pair in block
            for field in pair.values()
        )

    def _resolve_pair(
        self, pair: dict[str, str], sub: dict[str, Any]
    ) -> dict[str, str]:
        """
        Format one condition/value pair against a substitution.

        The ``condition`` key is omitted when the pair declares no condition
        or it substitutes to empty — a conditionless row emits a bare
        ``<value>``. An empty ``value`` is preserved as an explicit terminator.

        :param pair: A {condition, value} template dict.
        :param sub: Substitution dictionary for formatting.
        :return: Formatted value dict.
        """
        resolved = {"value": self.substitute(pair.get("value", ""), sub)}
        condition = self.substitute(pair.get("condition", ""), sub)
        if condition:
            resolved["condition"] = condition
        return resolved

    def _expand_blocks(
        self,
        blocks: list[list[dict[str, str]]],
        subs: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """
        Expand blocks into a flat value list, in declared order. A block
        bearing any placeholder expands once per substitution, as a unit; a
        placeholder-free block emits once, in place. Duplicate rows are
        collapsed to first occurrence — see ``_dedup_rows``.

        :param blocks: Normalised list of blocks.
        :param subs: Substitution group (may be empty).
        :return: Flat list of formatted value dicts.
        """
        flattened = []
        for block in blocks:
            if self._block_has_placeholder(block):
                for sub in subs:
                    flattened.extend(self._resolve_pair(p, sub) for p in block)
            else:
                flattened.extend(self._resolve_pair(p, {}) for p in block)
        return self._dedup_rows(flattened)
    
    @staticmethod
    def _dedup_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """
        Drop later rows whose (condition, value) duplicates an earlier row.
        Kodi's cascade picks the first match, so duplicates are dead code.

        :param rows: Flat list of resolved {condition, value} dicts.
        :return: Filtered list preserving first occurrences.
        """
        seen = set()
        result = []
        for row in rows:
            key = (row.get("condition", ""), row["value"])
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result
