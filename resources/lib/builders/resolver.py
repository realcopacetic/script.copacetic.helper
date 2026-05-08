# author: realcopacetic
"""
Configs and controls resolvers.

Pure resolution from pre-merged template data — no IO. Loading is the
caller's responsibility (see templates.py). Resolvers are constructed
fresh per Dynamic Editor session and discarded with the manager that
owns them.
"""

from typing import Iterator

from resources.lib.builders.logic import RuleEngine
from resources.lib.builders.substitution import enumerate_mapping_subs
from resources.lib.shared import logger as log


class ConfigsResolver:
    """
    Resolves configs from pre-merged template data on demand, with caching.
    Replaces the build-time ConfigsBuilder + configs.json file. Takes
    pre-merged template data; loading is the caller's responsibility.
    """

    def __init__(self, mappings: dict, configs_data: dict) -> None:
        """
        Build the reverse index. Resolution is lazy; entries are resolved
        on first access and cached.

        :param mappings: Dictionary of mapping definitions.
        :param configs_data: {mapping_name: {tpl_name: tpl_data}}.
        """
        self._mappings = mappings
        self._rules = RuleEngine()
        self._templates = {
            (mapping_name, tpl_name): tpl_data
            for mapping_name, templates in configs_data.items()
            for tpl_name, tpl_data in templates.items()
        }
        self._index = self._build_index()
        self._cache: dict[str, dict] = {}

    def _build_index(self) -> dict:
        """
        Build reverse index resolved_cfg_key → (mapping_name, tpl_name, sub).
        Iterates every (template × substitution) without resolving rules.

        :return: Index mapping cfg keys to template + sub origin.
        """
        index = {}
        for (mapping_name, tpl_name), _data in self._templates.items():
            # Constant template name — one entry, empty sub. Rules using
            # placeholders will KeyError loudly at resolve time.
            if "{" not in tpl_name:
                index[tpl_name] = (mapping_name, tpl_name, {})
                continue
            for sub in enumerate_mapping_subs(self._mappings.get(mapping_name, {})):
                try:
                    cfg_key = tpl_name.format(**sub)
                except KeyError as e:
                    log.debug(
                        f"{self.__class__.__name__}: template '{tpl_name}' "
                        f"in mapping '{mapping_name}' references unknown "
                        f"placeholder {e}; skipping for sub={sub}"
                    )
                    continue
                index[cfg_key] = (mapping_name, tpl_name, sub)
        return index

    def resolve(self, cfg_key: str) -> dict:
        """
        Resolve a single config entry by its fully-expanded key.
        Unknown keys are cached as ``{}`` so repeated misses are O(1)

        :param cfg_key: Resolved config key (e.g. "movies_layout").
        :return: Resolved entry dict, or empty dict if unknown.
        """
        if not cfg_key:
            return {}
        if cfg_key in self._cache:
            return self._cache[cfg_key]
        entry = self._index.get(cfg_key)
        if entry is None:
            self._cache[cfg_key] = {}
            return {}
        mapping_name, tpl_name, sub = entry
        result = self._resolve_one(
            self._templates[(mapping_name, tpl_name)], sub, mapping_name
        )
        self._cache[cfg_key] = result
        return result

    def resolve_default(self, cfg_key: str) -> str | None:
        """
        Resolve the default value for a config entry, falling back to the
        first available item if no default is explicitly set.

        :param cfg_key: Resolved config key.
        :return: Default value, first item, or None.
        """
        cfg = self.resolve(cfg_key)
        return cfg.get("default") or next(iter(cfg.get("items", [])), None)

    def iter_static_defaults(self) -> Iterator[tuple[str, str]]:
        """
        Yield (cfg_key, default) for every resolved static-mode entry that
        has a default. Used by initialize_skinstrings.

        :return: Iterator of (cfg_key, default_value) pairs.
        """
        for cfg_key in self._index:
            cfg = self.resolve(cfg_key)
            if cfg.get("mode") != "static":
                continue
            default = cfg.get("default")
            if default is not None:
                yield cfg_key, default

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
            "mode": "static",
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

        out: dict = {"items": items, "mode": merged["mode"]}
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


class ControlsResolver:
    """
    Resolves controls from pre-merged template data on demand.
    """

    def __init__(self, mappings: dict, controls_data: dict) -> None:
        """
        Store templates as a flat list. Resolved on demand per
        mapping-set; typically called once per editor session.

        :param mappings: Dictionary of mapping definitions.
        :param controls_data: {mapping_name: {tpl_name: tpl_data}}.
        """
        self._mappings = mappings
        self._templates = [
            (mapping_name, tpl_name, tpl_data)
            for mapping_name, templates in controls_data.items()
            for tpl_name, tpl_data in templates.items()
        ]

    def for_mappings(self, mapping_keys: list[str]) -> dict:
        """
        Return resolved controls declared under any of the given mappings.

        :param mapping_keys: Mapping names to include in the result.
        :return: Mapping of resolved control name → resolved control dict.
        """
        keys = set(mapping_keys)
        resolved: dict = {}
        for mapping_name, tpl_name, tpl_data in self._templates:
            if mapping_name not in keys:
                continue
            resolved.update(self._expand(mapping_name, tpl_name, tpl_data))
        return resolved

    def _expand(self, mapping_name: str, template_name: str, data: dict) -> dict:
        """
        Expand one control template into resolved form(s). Dynamic-mode is
        passthrough; static contextual_bindings expand the bindings list;
        plain static templates expand template name and string fields.

        :param mapping_name: Mapping owning this template.
        :param template_name: Template control name.
        :param data: Template data dict.
        :return: Mapping of resolved name → resolved control dict.
        """
        if data.get("mode") == "dynamic":
            return {template_name: {"mapping": mapping_name, **data}}

        substitutions = enumerate_mapping_subs(self._mappings.get(mapping_name, {}))

        if "contextual_bindings" in data:
            resolved_bindings: list = []
            seen: set = set()
            for sub in substitutions:
                resolved = {
                    k: (v.format(**sub) if isinstance(v, str) else v)
                    for k, v in data["contextual_bindings"].items()
                }
                key = tuple(sorted(resolved.items()))
                if key not in seen:
                    seen.add(key)
                    resolved_bindings.append(resolved)
            return {
                template_name: {
                    "mapping": mapping_name,
                    **{k: v for k, v in data.items() if k != "contextual_bindings"},
                    "contextual_bindings": resolved_bindings,
                }
            }

        return {
            template_name.format(**sub): {
                "mapping": mapping_name,
                **{
                    k: (v.format(**sub) if isinstance(v, str) else v)
                    for k, v in data.items()
                },
            }
            for sub in substitutions
        }
