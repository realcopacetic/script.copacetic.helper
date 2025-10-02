# author: realcopacetic

import sys
from typing import Callable

from resources.lib.shared.parser import parse_params
from resources.lib.shared.utilities import log


class Main:
    """Entry point for scripts. Parses argv, dispatches actions via REGISTRY."""

    def __init__(self, registry: dict[str, Callable]) -> None:
        self._registry = registry
        self._parse_argv()
        action = self.params.pop("action", "").strip()
        if not action:
            log("No 'action' provided; aborting.")
            return

        if (fn := self._dispatch(action)) is None:
            log(f"Unknown action: {fn}")
            return

        kwargs = {k: v for k, v in self.params.items() if not k.startswith("_")}
        try:
            fn(**kwargs)
            log(f"Script ran action '{action}' with params: {kwargs}")
        except TypeError as e:
            log(f"Action '{action}' arg mismatch: {e}")
        except Exception as e:
            log(f"Action '{action}' raised: {e}")

    def _parse_argv(self) -> dict[str, str]:
        """
        The parser accepts both plugin-style querystrings and RunScript k=v tokens,
        preserves literal '+', tolerates raw '&' and commas in values, and percent-decodes.
        """
        try:
            self.params = parse_params(sys.argv, mode="script")
        except Exception as e:
            log(f"_parse_argv error: {e}")
            self.params = {}

    def _dispatch(self, action: str) -> Callable | None:
        """
        Resolve an action name to a callable from the provided registry.

        Returns None if the action is not registered.
        """
        return self._registry.get(action)
