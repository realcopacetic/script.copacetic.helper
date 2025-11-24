# author: realcopacetic
from __future__ import annotations

import json
from typing import Any

from resources.lib.shared.sqlite import TmdbCacheHandler
from resources.lib.shared import logger as log


class TmdbCache:
    """
    Thin facade around TmdbCacheHandler.

    Stores and retrieves canonical TMDb payloads (dicts) per
    (dbtype, tmdb_id, language). TTL and purge behaviour are handled
    by the underlying TmdbCacheHandler.
    """

    def __init__(self, handler: TmdbCacheHandler | None = None) -> None:
        self._handler = handler or TmdbCacheHandler()

    def get(
        self,
        dbtype: str,
        tmdb_id: int,
        language: str,
    ) -> dict[str, Any] | None:
        """
        Return the cached canonical payload dict for (dbtype, tmdb_id, language),
        or None if no fresh entry exists.
        """
        row = self._handler.get_entry(dbtype, tmdb_id, language)
        if not row:
            return None

        payload = row.get("payload")
        if isinstance(payload, dict):
            return payload

        # Defensive: if something odd slips through, log + treat as miss.
        log.debug(
            f"TmdbCache.get → unexpected payload type for "
            f"{dbtype=}, {tmdb_id=}, {language=}: {type(payload)!r}"
        )
        return None

    def set(
        self,
        dbtype: str,
        tmdb_id: int,
        language: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Store a canonical TMDb payload for (dbtype, tmdb_id, language).
        """
        try:
            self._handler.upsert_entry(
                dbtype=dbtype,
                tmdb_id=tmdb_id,
                language=language,
                payload_json=json.dumps(payload),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug(
                f"TmdbCache.set → cache upsert failed for "
                f"{dbtype=}, {tmdb_id=}, {language=}: {exc}"
            )
