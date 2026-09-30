# author: realcopacetic

from typing import Callable

LOG_TAG = "plugin"
_INFO_TAG = "__plugin_info__"


class PluginInfoRegistry(type):
    """
    Metaclass that auto-tags all public methods as plugin info handlers,
    unless prefixed with '_'.
    """

    def __new__(mcls: type, name: str, bases: tuple[type, ...], namespace) -> type:
        for k, v in namespace.items():
            if callable(v) and not k.startswith("_"):
                setattr(v, _INFO_TAG, k)
        return super().__new__(mcls, name, bases, namespace)


def collect_info_handlers(inst: object) -> dict[str, Callable]:
    """
    Collect bound info handlers from a PluginHandlers instance.

    :param inst: PluginHandlers instance.
    :return: Mapping of info name to bound method.
    """
    return {
        tag: getattr(inst, attr)
        for attr, fn in type(inst).__dict__.items()
        if callable(fn) and (tag := getattr(fn, _INFO_TAG, None))
    }
