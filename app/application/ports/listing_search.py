from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.domain.listing_sources import CanonicalListingSnapshot, ListingSource


def _empty_terms() -> tuple[str, ...]:
    return ()


class ListingSearchType(StrEnum):
    SALE = "sale"
    RENT = "rent"


@dataclass(frozen=True)
class ListingSearchQuery:
    search_type: ListingSearchType
    locations: tuple[str, ...] = field(default_factory=_empty_terms)
    addresses: tuple[str, ...] = field(default_factory=_empty_terms)
    keywords: tuple[str, ...] = field(default_factory=_empty_terms)
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_beds: Decimal | None = None
    limit: int = 3


class ListingSearchClient(Protocol):
    async def search(
        self,
        *,
        source: ListingSource,
        query: ListingSearchQuery,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        raise NotImplementedError