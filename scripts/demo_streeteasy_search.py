"""Run a live StreetEasy search using the current listing-search adapter.

Usage:
    uv run python scripts/demo_streeteasy_search.py --location Bronx

Examples:
    uv run python scripts/demo_streeteasy_search.py --location Bronx --search-type sale --limit 3
    uv run python scripts/demo_streeteasy_search.py --location Bronx --search-type rent --limit 5
    uv run python scripts/demo_streeteasy_search.py \
        --location Bronx --min-price 250000 --max-price 700000 --min-beds 2
    uv run python scripts/demo_streeteasy_search.py --address "225 East 134th Street"
    uv run python scripts/demo_streeteasy_search.py \
        --location Bronx --keyword doorman --keyword co-op
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.listing_search import ListingSearchQuery, ListingSearchType
from app.core.config import get_settings
from app.domain.listing_sources import ListingSource, ListingSourceType
from app.infrastructure.listing_sources.streeteasy import (
    StreetEasyBlockedError,
    StreetEasyListingSearchClient,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live StreetEasy search using the current adapter."
    )
    parser.add_argument(
        "--location",
        help="Location slug input, e.g. Bronx or Riverdale.",
    )
    parser.add_argument(
        "--address",
        action="append",
        default=[],
        help="Street address quick-search term. Repeatable.",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword/property-type/amenity term. Repeatable.",
    )
    parser.add_argument(
        "--search-type",
        choices=[search_type.value for search_type in ListingSearchType],
        default=ListingSearchType.SALE.value,
        help="Whether to search sale or rent listings.",
    )
    parser.add_argument(
        "--min-price",
        type=_positive_decimal,
        help="Minimum listing price filter.",
    )
    parser.add_argument(
        "--max-price",
        type=_positive_decimal,
        help="Maximum listing price filter.",
    )
    parser.add_argument(
        "--min-beds",
        type=_positive_decimal,
        help="Minimum bedroom count filter.",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=3,
        help="Maximum number of listings to print.",
    )
    args = parser.parse_args(argv)
    if (
        args.min_price is not None
        and args.max_price is not None
        and args.min_price > args.max_price
    ):
        parser.error("--min-price cannot be greater than --max-price.")
    if not args.location and not args.address and not args.keyword:
        parser.error("provide at least one of --location, --address, or --keyword.")
    return args


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _positive_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("value must be a valid number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


async def _main() -> int:
    args = parse_args()
    settings = get_settings()
    client = StreetEasyListingSearchClient(
        timeout_seconds=settings.streeteasy_timeout_seconds,
        user_agent=settings.streeteasy_user_agent,
    )
    source = ListingSource(
        source_id=uuid4(),
        workspace_id=uuid4(),
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url=settings.streeteasy_base_url,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        enabled=True,
    )
    query = ListingSearchQuery(
        search_type=ListingSearchType(args.search_type),
        locations=(args.location,) if args.location else (),
        addresses=tuple(args.address),
        keywords=tuple(args.keyword),
        min_price=args.min_price,
        max_price=args.max_price,
        min_beds=args.min_beds,
        limit=args.limit,
    )

    filters: list[str] = [
        f"search_type={args.search_type}",
        f"limit={args.limit}",
    ]
    if args.location:
        filters.append(f"location={args.location!r}")
    if args.address:
        filters.append(f"addresses={args.address!r}")
    if args.keyword:
        filters.append(f"keywords={args.keyword!r}")
    if args.min_price is not None:
        filters.append(f"min_price={args.min_price}")
    if args.max_price is not None:
        filters.append(f"max_price={args.max_price}")
    if args.min_beds is not None:
        filters.append(f"min_beds={args.min_beds}")

    print(f"Searching StreetEasy: {', '.join(filters)}")

    try:
        results = await client.search(source=source, query=query)
    except StreetEasyBlockedError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client._client.aclose()

    print(f"Found {len(results)} listing(s)")
    for index, listing in enumerate(results, start=1):
        print(f"\n[{index}] {listing.address_text or listing.title or listing.source_url}")
        print(f"  url: {listing.source_url}")
        print(f"  price: {listing.price}")
        print(f"  beds: {listing.beds}")
        print(f"  baths: {listing.baths}")
        print(f"  property_type: {listing.property_type}")
        if listing.image_urls:
            print(f"  image: {listing.image_urls[0]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))