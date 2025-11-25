# author: realcopacetic

from typing import Any

from resources.lib.shared.sqlite import TmdbCacheHandler
from resources.lib.shared import logger as log


class TmdbCache:
    """
    TMDb response cache facade. Wraps TmdbCacheHandler to store canonical 
    payloads keyed by (dbtype, tmdb_id, language).
    """

    def __init__(self, handler: TmdbCacheHandler | None = None) -> None:
        """
        Initialise the TMDb cache facade.

        :param handler: Optional preconfigured TmdbCacheHandler instance.
        """
        self._handler = handler or TmdbCacheHandler()

    def get(
        self,
        dbtype: str,
        tmdb_id: int,
        language: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve a cached TMDb payload.

        :param dbtype: TMDb database type (for example, "movie" or "tv").
        :param tmdb_id: Numeric TMDb identifier for the requested item.
        :param language: TMDb language/region code (for example, "en-US").
        :return: Canonical payload dict if present and fresh, otherwise ``None``.
        """
        row = self._handler.get_entry(dbtype, tmdb_id, language)
        if not row:
            return None

        payload = row.get("payload")
        if isinstance(payload, dict):
            return payload

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
        Store a TMDb payload in the cache.

        :param dbtype: TMDb database type (for example, "movie" or "tv").
        :param tmdb_id: Numeric TMDb identifier for the item being cached.
        :param language: TMDb language/region code (for example, "en-US").
        :param payload: Canonical TMDb response payload as a dict.
        """
        try:
            self._handler.upsert_entry(
                dbtype=dbtype,
                tmdb_id=tmdb_id,
                language=language,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug(
                f"TmdbCache.set → cache upsert failed for "
                f"{dbtype=}, {tmdb_id=}, {language=}: {exc}"
            )
