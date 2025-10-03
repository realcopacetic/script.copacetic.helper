# author: realcopacetic

from typing import Callable


_INFO_TAG = "__plugin_info__"
_NOINFO_TAG = "__no_info__"


def no_info(fn: Callable) -> Callable:
    """
    Decorator to opt a method out of being an info handler.

    :param fn: Method to mark as excluded.
    :returns: Same method, tagged as no-info.
    """
    setattr(fn, _NOINFO_TAG, True)
    return fn


class PluginInfoRegistry(type):
    """
    Metaclass that auto-tags all public methods as plugin info handlers,
    unless explicitly marked with @no_info or prefixed with '_'.
    """

    def __new__(mcls, name, bases, namespace):
        for k, v in namespace.items():
            if (
                callable(v)
                and not k.startswith("_")
                and not getattr(v, _NOINFO_TAG, False)
            ):
                setattr(v, _INFO_TAG, k)
        return super().__new__(mcls, name, bases, namespace)


def collect_info_handlers(inst: object) -> dict[str, Callable]:
    """
    Collect bound info handlers from a PluginHandlers instance.

    :param inst: PluginHandlers instance.
    :returns: Mapping of info name to bound method.
    """
    return {
        getattr(fn, _INFO_TAG): fn
        for attr in dir(inst)
        if callable(fn := getattr(inst, attr)) and getattr(fn, _INFO_TAG, None)
    }
