"""Build a complete season/episode skeleton from TMDb catalog data.

Merges the authoritative TMDb episode list with whatever provider-sourced
AggregatedEpisode entries already exist. Episodes absent from provider data
become placeholder rows (match_id="", subtitles_count=0) that the UI renders
greyed-out. Season-pack entries (episode=None) are preserved at season level.
"""

from __future__ import annotations

from .types import AggregatedEpisode, AggregatedSeason


def build_season_skeleton(
    tmdb_catalog: list[tuple[int, list[dict]]],
    existing_seasons: list[AggregatedSeason],
) -> list[AggregatedSeason]:
    """Merge TMDb episode catalog with provider-sourced seasons.

    Args:
        tmdb_catalog: [(season_number, [{episode_number, name, air_date}])]
        existing_seasons: seasons produced by the aggregator from provider data

    Returns:
        Merged season list, sorted by season_number ascending.
    """
    # Index existing data for fast lookup
    existing_by_season: dict[int, AggregatedSeason] = {
        s.season_number: s for s in existing_seasons
    }
    existing_ep_by_key: dict[tuple[int, int], AggregatedEpisode] = {}
    season_packs_by_season: dict[int, list[AggregatedEpisode]] = {}

    for season in existing_seasons:
        for ep in season.episodes:
            if ep.season is not None and ep.episode is not None:
                existing_ep_by_key[(ep.season, ep.episode)] = ep
            elif ep.season is not None:
                season_packs_by_season.setdefault(ep.season, []).append(ep)

    tmdb_season_numbers = {s for s, _ in tmdb_catalog}
    merged: dict[int, AggregatedSeason] = {}

    for season_no, tmdb_episodes in tmdb_catalog:
        packs = season_packs_by_season.get(season_no, [])
        provider_season = existing_by_season.get(season_no)
        subtitles_count = provider_season.subtitles_count if provider_season else sum(
            ep.subtitles_count for ep in packs
        )

        episodes: list[AggregatedEpisode] = list(packs)
        for ep_data in tmdb_episodes:
            ep_no = ep_data.get("episode_number")
            if not isinstance(ep_no, int):
                continue
            key = (season_no, ep_no)
            if key in existing_ep_by_key:
                episodes.append(existing_ep_by_key[key])
            else:
                episodes.append(
                    AggregatedEpisode(
                        season=season_no,
                        episode=ep_no,
                        title=ep_data.get("name") or "",
                        match_id=f"skeleton:{season_no}:{ep_no}",
                        year=_year_from_air_date(ep_data.get("air_date")),
                        subtitles_count=0,
                        providers=(),
                    )
                )

        episodes.sort(key=lambda ep: (ep.episode is None, ep.episode or 0))
        merged[season_no] = AggregatedSeason(
            season_number=season_no,
            episodes=episodes,
            subtitles_count=subtitles_count,
        )

    # Preserve provider seasons that TMDb doesn't know about (e.g. extras/specials)
    for season in existing_seasons:
        if season.season_number not in tmdb_season_numbers:
            merged[season.season_number] = season

    return [merged[n] for n in sorted(merged)]


def _year_from_air_date(air_date: str | None) -> int | None:
    if not air_date or len(air_date) < 4:
        return None
    try:
        return int(air_date[:4])
    except ValueError:
        return None
