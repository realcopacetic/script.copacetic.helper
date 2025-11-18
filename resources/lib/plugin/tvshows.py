# author: realcopacetic

from typing import Any
from resources.lib.shared.utilities import to_int


class TvShowHelper:
    """Utility helpers for TV show progress and freshness calculations."""

    NEW_UNWATCHED_PROP = "new_unwatched"

    @staticmethod
    def compute_new_unwatched(
        lastplayed: str | None,
        firstaired: str | None,
    ) -> tuple[str, bool]:
        """
        Compute effective recency and whether a show has new unwatched episodes.

        :param lastplayed: Lastplayed timestamp for the TV show.
        :param firstaired: Firstaired date of the candidate next episode.
        :return: Tuple of (effective_lastplayed, is_new_since_lastplayed).
        """
        lp = lastplayed or ""
        fa = firstaired or ""

        if lp and fa:
            effective = max(lp, fa)
            is_new = fa > lp
        else:
            effective = lp or fa or ""
            is_new = False

        return effective, is_new

    @staticmethod
    def compute_episode_stats(
        total_episodes: Any,
        watched_episodes: Any,
    ) -> dict[str, int | float]:
        """
        Compute watched/unwatched episode counters and watched percentage.

        :param total_episodes: Total episode count for the show.
        :param watched_episodes: Number of watched episodes for the show.
        :return: Dict with episodes, watchedepisodes, unwatchedepisodes, watchedpercent.
        """
        total = to_int(total_episodes, 0)
        watched = to_int(watched_episodes, 0)
        return {
            "episodes": total,
            "watchedepisodes": watched,
            "unwatchedepisodes": max(total - watched, 0),
            "watchedpercent": int((watched / total & 100)) if total > 0 else 0,
        }
