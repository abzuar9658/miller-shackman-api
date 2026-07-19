"""Quick StreetEasy search smoke test for a structured query.

Usage:
    uv run python scripts/test_streeteasy_search.py "Manhattan" rent
    uv run python scripts/test_streeteasy_search.py "420 East 72nd Street" sale
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.listing_search import ListingSearchQuery, ListingSearchType
from app.domain.listing_sources import ListingSource, ListingSourceType
from app.infrastructure.listing_sources.streeteasy.client import StreetEasyListingSearchClient


def _build_source(base_url: str) -> ListingSource:
    now = datetime.now(UTC)
    return ListingSource(
        source_id=uuid4(),
        workspace_id=uuid4(),
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url=base_url,
        created_at=now,
        updated_at=now,
        enabled=True,
        terms_reviewed_at=now,
        data_use_policy="Reviewed for optional enrichment.",
    )


async def _main() -> int:
    location = sys.argv[1] if len(sys.argv) > 1 else "Manhattan"
    search_type_input = sys.argv[2] if len(sys.argv) > 2 else "rent"
    search_type = ListingSearchType.RENT if search_type_input == "rent" else ListingSearchType.SALE

    query = ListingSearchQuery(
        search_type=search_type,
        locations=(location,),
        keywords=("apartments",),
        limit=5,
    )
    source = _build_source("https://streeteasy.com")
    client = StreetEasyListingSearchClient()

    print(f"Searching StreetEasy: {query.search_type.value} in {location}")
    kind = "for-rent" if search_type == ListingSearchType.RENT else "for-sale"
    slug = location.lower().replace(" ", "-")
    print(f"URL will be: https://streeteasy.com/{kind}/{slug}")
    print()

    try:
        results = await client.search(source=source, query=query)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1

    if not results:
        print("No results returned.")
        return 0

    print(f"Found {len(results)} result(s):")
    for idx, snapshot in enumerate(results, 1):
        print(f"\n{idx}. {snapshot.title}")
        print(f"   Address: {snapshot.address_text}")
        print(f"   Neighborhood: {snapshot.neighborhood}")
        print(f"   Price: {snapshot.price}")
        print(f"   Beds: {snapshot.beds}, Baths: {snapshot.baths}")
        print(f"   URL: {snapshot.source_url}")
        print(f"   Status: {snapshot.status.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
