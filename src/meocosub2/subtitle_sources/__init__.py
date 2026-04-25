"""Subtitle source aggregation exports."""

from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.types import (
    AggregatedEpisode,
    AggregatedSearchCatalog,
    AggregatedSeason,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    AggregatedWork,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
    SubtitleSourceProvider,
    WorkChip,
)

__all__ = [
    "AggregatedEpisode",
    "AggregatedSearchCatalog",
    "AggregatedSeason",
    "AggregatedSubtitleResult",
    "AggregatedTitleMatch",
    "AggregatedWork",
    "ProviderSearchCatalog",
    "ProviderSubtitleMatch",
    "ProviderSubtitleResult",
    "SubtitleSearchAggregator",
    "SubtitleSourceProvider",
    "WorkChip",
]
