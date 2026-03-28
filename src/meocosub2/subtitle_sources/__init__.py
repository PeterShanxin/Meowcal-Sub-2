"""Subtitle source aggregation exports."""

from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.types import (
    AggregatedSearchCatalog,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
    SubtitleSourceProvider,
)

__all__ = [
    "AggregatedSearchCatalog",
    "AggregatedSubtitleResult",
    "AggregatedTitleMatch",
    "ProviderSearchCatalog",
    "ProviderSubtitleMatch",
    "ProviderSubtitleResult",
    "SubtitleSearchAggregator",
    "SubtitleSourceProvider",
]
