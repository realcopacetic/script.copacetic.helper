# author: realcopacetic

import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache, wraps
from typing import Any, Callable, Iterator

import xbmc
from xbmcaddon import Addon

ADDON = Addon()
ADDON_ID = ADDON.getAddonInfo("id")

DEBUG = xbmc.LOGDEBUG
INFO = xbmc.LOGINFO
WARNING = xbmc.LOGWARNING
ERROR = xbmc.LOGERROR

_MUTED = ContextVar("log_muted", default=False)


@contextmanager
def muted() -> Iterator[None]:
    """
    Drop DEBUG-level logs in the current context for the duration of the block.
    force=True and INFO/WARNING/ERROR lines pass through unaffected.
    """
    token = _MUTED.set(True)
    try:
        yield
    finally:
        _MUTED.reset(token)


@cache
def debug_logging() -> bool:
    """
    The add-on's debug_logging setting, read once per process.
    Long-lived callers clear it with ``debug_logging.cache_clear()``.
    """
    return ADDON.getSettingBool("debug_logging")


def log(message: str, level: int = DEBUG, force: bool = False) -> None:
    """
    Logs a message with addon prefix, respecting log level and debug settings.
    If force is true or debug_logging enabled in addon, DEBUG logs are elevated
    to INFO, ensuring they will be logged regardless of Kodi global settings.

    :param message: Message string.
    :param level: Kodi log level constant.
    :param force: If True, logs regardless of settings.
    """
    if level == DEBUG and not force and _MUTED.get():
        return
    if level == DEBUG and (force or debug_logging()):
        level = INFO
    xbmc.log(f"{ADDON_ID} → {message}", level)


def debug(message: str, force: bool = False) -> None:
    """
    Logs a DEBUG-level message. Visible only when Kodi's component log
    level is debug, unless `debug_logging` is enabled (which elevates it
    to INFO) or `force` is true.

    :param message: Message string.
    :param force: If True, logs regardless of settings.
    """
    log(message, level=DEBUG, force=force)


def info(message: str) -> None:
    """
    Logs an INFO-level message. Always visible at Kodi's default log level.

    :param message: Message string.
    """
    log(message, level=INFO)


def verbose(message: str) -> None:
    """
    Logs detailed per-iteration diagnostic output, gated behind the
    `verbose_logging` setting. Dropped entirely when off.

    :param message: Message string.
    """
    if not ADDON.getSettingBool("verbose_logging"):
        return

    log(message, level=INFO)


def warning(message: str) -> None:
    """
    Logs a WARNING-level message. Always visible at Kodi's default log level.
    Use for unexpected but non-fatal conditions.

    :param message: Message string.
    """
    log(message, level=WARNING)


def error(message: str) -> None:
    """
    Logs an ERROR-level message. Always visible at Kodi's default log level.
    Use for failures that prevent intended behaviour from completing.

    :param message: Message string.
    """
    log(message, level=ERROR)


def execute(action: str, wait: bool = False) -> None:
    """
    Logs and executes a built-in Kodi command.

    :param action: Built-in Kodi command string.
    :param wait: Block until the main thread has processed the command.
    """

    log(f"Executed action: {action}", DEBUG)
    xbmc.executebuiltin(action, wait)


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
