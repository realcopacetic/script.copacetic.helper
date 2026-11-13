# author: realcopacetic

import json
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, to_int

USER_AGENT = (
    f"script.copacetic.helper/{ADDON.getAddonInfo('version')}"
    " ( https://github.com/realcopacetic/script.copacetic.helper )"
)


MAX_BODY = 8_000_000  # bytes read of an answer; a longer one is cut short


class HttpError(Exception):
    """
    A failed request: HTTP status (None when unreachable), seconds to wait and the
    error body's "code" ("" when none).
    """

    def __init__(
        self, status: int | None, retry_after: int = 0, code: str = ""
    ) -> None:
        super().__init__(status)
        self.status, self.retry_after, self.code = status, retry_after, code


def _error_code(exc: HTTPError) -> str:
    """The error body's top-level "code" (TheIntroDB's reason), "" when none."""
    try:
        return str(json.loads(exc.read(MAX_BODY)).get("code") or "")
    except (OSError, ValueError, AttributeError, RecursionError, HTTPException):
        return ""  # unreadable, not JSON, or not an object


def get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 5,
    body: Any = None,
) -> Any:
    """
    GET url with params (POST body as JSON when given) and decode its JSON, sending
    the helper's contact User-Agent. Logs one debug line: status and path.

    :param url: Endpoint URL without a query string.
    :param params: Query parameters.
    :param headers: Extra headers (e.g. Authorization).
    :param timeout: Seconds to wait for the server.
    :param body: JSON-serialisable request body; makes the request a POST.
    :return: Decoded JSON.
    :raises HttpError: On an HTTP error status, no connection or bad JSON.
    """
    request = Request(
        f"{url}?{urlencode(params)}" if params else url,
        None if body is None else json.dumps(body).encode(),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    path = urlsplit(url).path
    try:
        with urlopen(request, timeout=timeout) as response:
            log.debug(f"get_json → {response.status} {path}")
            return json.loads(response.read(MAX_BODY))  # cut short: bad JSON
    except HTTPError as exc:  # before OSError: it is one
        log.debug(f"get_json → {exc.code} {path}")
        wait = exc.headers.get("Retry-After") or exc.headers.get("X-RateLimit-Reset-In")
        raise HttpError(exc.code, to_int(wait), _error_code(exc)) from None
    except (OSError, ValueError, RecursionError, HTTPException) as exc:
        # URLError, timeout; bad JSON; a body cut short (IncompleteRead)
        log.debug(f"get_json → {exc!r} {path}")
        raise HttpError(None) from None
