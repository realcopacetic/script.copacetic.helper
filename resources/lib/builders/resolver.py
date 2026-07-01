# author: realcopacetic
"""
Configs and controls resolvers.

Pure resolution from pre-merged template data — no IO. Loading is the
caller's responsibility (see templates.py). Resolvers are constructed
fresh per Dynamic Editor session and discarded with the manager that
owns them.
"""

from resources.lib.builders.logic import RuleEngine
from resources.lib.shared import logger as log


class _TemplateResolver:
    """
    Shared template storage for resolver classes.
    """

    def __init__(self, mappings: dict, data: dict) -> None:
        """
        Flatten template data into a (mapping_name, tpl_name) → data dict.

        :param mappings: Dictionary of mapping definitions.
        :param data: {mapping_name: {tpl_name: tpl_data}}.
        """
        self._mappings = mappings
        self._templates = {
            (mapping_name, tpl_name): tpl_data
            for mapping_name, templates in data.items()
            for tpl_name, tpl_data in templates.items()
        }


class ConfigsResolver(_TemplateResolver):
    """
    Resolves configs from pre-merged template data on demand. Callers
    provide the substitution context per resolve; no eager enumeration.
    """

    def __init__(self, mappings: dict, configs_data: dict) -> None:
        """
        Store templates and initialise the rule engine.

        :param mappings: Dictionary of mapping definitions.
        :param configs_data: {mapping_name: {tpl_name: tpl_data}}.
        """

        super().__init__(mappings, configs_data)
        self._rules = RuleEngine()

    def resolve(self, mapping_name: str, tpl_name: str, sub: dict) -> dict:
        """
        Resolve a template against a substitution dict. Tries the
        formatted template name first (constant-named templates), then
        falls back to the raw template name (placeholder templates).

        :param mapping_name: Mapping owning the template.
        :param tpl_name: Raw template name (placeholders intact).
        :param sub: Substitution dict.
        :return: Resolved entry dict, or empty dict if no match.
        """
        try:
            formatted = tpl_name.format(**sub)
        except KeyError:
            formatted = None

        if formatted is not None:
            if data := self._templates.get((mapping_name, formatted)):
                return self._resolve_one(data, sub, mapping_name)

        if data := self._templates.get((mapping_name, tpl_name)):
            return self._resolve_one(data, sub, mapping_name)

        return {}

    def resolve_default(
        self, mapping_name: str, tpl_name: str, sub: dict
    ) -> str | None:
        """
        Resolve the default for a template+sub, falling back to the
        first available item if no default is explicitly set.

        :param mapping_name: Mapping owning the template.
        :param tpl_name: Raw template name (placeholders intact).
        :param sub: Substitution dict.
        :return: Default value, first item, or None.
        """
        cfg = self.resolve(mapping_name, tpl_name, sub)
        default = cfg.get("default") or next(iter(cfg.get("items", [])), None)
        if default is None:
            log.warning(
                f"{self.__class__.__name__}: '{tpl_name}' resolved no items "
                f"for '{mapping_name}/{sub.get('mapping_item', '?')}' — "
                f"field will be absent from substitutions."
            )
        return default

    def dependent_fields(self, mapping_name: str, tpl_name: str) -> list[str]:
        """
        Sibling fields a config declares a dependency on, used to sequence
        entry field resolution order.

        :param mapping_name: Mapping owning the template.
        :param tpl_name: Config template name.
        :return: List of field names, empty if none declared.
        """
        return (self._templates.get((mapping_name, tpl_name)) or {}).get(
            "dependent_fields", []
        )

    def _resolve_one(self, data: dict, sub: dict, mapping_name: str) -> dict:
        """
        Resolve one template against one sub: filter items by rules, attach
        labels, choose a default.

        :param data: Raw template data.
        :param sub: Substitution dict.
        :param mapping_name: Mapping owning this template.
        :return: Resolved entry dict.
        """
        template_defaults = {
            "items": [],
            "filter_mode": "exclude",
            "rules": [],
        }
        merged = {**template_defaults, **data}

        raw_items = merged["items"]
        if isinstance(raw_items, dict):
            items_list = list(raw_items.keys())
            labels = {k: v for k, v in raw_items.items() if v}
        else:
            items_list = raw_items
            labels = {}

        excluded = {
            value
            for rule in merged["rules"]
            if self._rules.evaluate(rule["condition"].format(**sub))
            for value in rule.get("value", [])
        }
        items = [
            item
            for item in items_list
            if (item not in excluded) == (merged["filter_mode"] == "exclude")
        ]

        out: dict = {"items": items}
        if labels:
            out["labels"] = labels

        defaults_map = data.get("defaults") or {}
        if defaults_map:
            mapping = self._mappings.get(mapping_name, {})
            default_key = data.get("default_key") or mapping.get(
                "placeholders", {}
            ).get("key")
            lookup = sub.get(default_key, "") if default_key else ""
            default_value = defaults_map.get(lookup) or defaults_map.get("*")
            if default_value not in items:
                default_value = items[0] if items else None
            if default_value is not None:
                out["default"] = default_value

        return out


class ControlsResolver(_TemplateResolver):
    """
    Resolves controls from pre-merged template data on demand. All controls
    are dynamic field-bound; resolution tags each with its owning mapping.
    """

    def for_mappings(self, mapping_keys: list[str]) -> dict:
        """
        Return resolved controls declared under any of the given mappings.

        :param mapping_keys: Mapping names to include in the result.
        :return: Mapping of resolved control name → resolved control dict.
        """
        keys = set(mapping_keys)
        return {
            tpl_name: {"mapping": mapping_name, **tpl_data}
            for (mapping_name, tpl_name), tpl_data in self._templates.items()
            if mapping_name in keys
        }
