# author: realcopacetic

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

import xbmc

from resources.lib.shared.utilities import ADDON, ADDON_ID

DEBUG = xbmc.LOGDEBUG
INFO = xbmc.LOGINFO
WARNING = xbmc.LOGWARNING
ERROR = xbmc.LOGERROR


def log(message: str, level: int = DEBUG, force: bool = False):
    """
    Logs a message with addon prefix, respecting log level and debug settings.
    If force is true or debug_logging enabled in addon, DEBUG logs are elevated
    INFO, ensuring they will be logged regardless of Kodi global settings.


    :param message: Message string.
    :param level: Kodi log level constant.
    :param force: If True, logs regardless of settings.
    """
    if (ADDON.getSettingBool("debug_logging") or force) and level == DEBUG:
        level = INFO
    xbmc.log(f"{ADDON_ID} → {message}", level)


def debug(message: str, force: bool = False):
    log(message, loglevel=DEBUG, force=force)


def info(message: str):
    log(message, loglevel=INFO)


def warn(message: str):
    log(message, loglevel=WARNING)


def error(message: str):
    log(message, loglevel=ERROR)


def execute(action: str) -> None:
    """
    Logs and executes a built-in Kodi command.

    :param action: Built-in Kodi command string.
    """
    log(f"Executed action: {action}", DEBUG)
    xbmc.executebuiltin(action)


def duration(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that logs the execution time of a method.

    :param func: The method to wrap.
    :return: Wrapped method with timing log.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        cls_name = args[0].__class__.__name__ if args else "UnknownClass"
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        log(f"{cls_name} → {func.__name__} took {duration:.4f} seconds", DEBUG)
        return result

    return wrapper
