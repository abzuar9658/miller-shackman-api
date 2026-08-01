from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.application.ports.listing_search import ListingSearchQuery, ListingSearchType
from app.domain.listing_sources import ListingSource, ListingSourceType
from app.infrastructure.listing_sources.streeteasy import (
    StreetEasyBlockedError,
    StreetEasyListingSearchClient,
)
from app.infrastructure.listing_sources.streeteasy.client import _build_search_url

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
HTML = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "item": {
        "@type": "SingleFamilyResidence",
        "name": "Single-family house in Throgs Neck",
        "url": "https://streeteasy.com/building/2738-miles-avenue-bronx/1",
        "image": ["https://img.example/1.jpg"],
        "description": "Renovated detached brick home.",
        "address": {
          "streetAddress": "2738 Miles Avenue",
          "addressLocality": "Bronx",
          "addressRegion": "NY",
          "postalCode": "10465"
        },
        "offers": {"@type": "Offer", "price": "650000"},
        "numberOfBedrooms": "4",
        "numberOfBathroomsTotal": "1"
      }
    }
  ]
}
</script></head><body></body></html>
"""


def _source() -> ListingSource:
    return ListingSource(
        source_id=uuid4(),
        workspace_id=uuid4(),
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_search_parses_json_ld_listing_results(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(200, text=HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)
    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            locations=("Bronx",),
            limit=3,
        ),
    )

    assert len(results) == 1
    assert results[0].external_listing_id == "1"
    assert results[0].price is not None
    assert results[0].address_text == "2738 Miles Avenue, Bronx, NY, 10465"


HTML_WITH_URLLESS_OBJECT = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "StreetEasy"
}
</script><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SingleFamilyResidence",
  "name": "Listed home",
  "url": "https://streeteasy.com/building/listed-home-bronx/2",
  "address": {
    "streetAddress": "1000 Test Avenue",
    "addressLocality": "Bronx",
    "addressRegion": "NY",
    "postalCode": "10465"
  },
  "offers": {"@type": "Offer", "price": "550000"},
  "numberOfBedrooms": "2",
  "numberOfBathroomsTotal": "1"
}
</script></head><body></body></html>
"""


async def test_search_skips_json_ld_objects_without_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(200, text=HTML_WITH_URLLESS_OBJECT, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)
    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            locations=("Bronx",),
            limit=3,
        ),
    )

    assert len(results) == 1
    assert results[0].external_listing_id == "2"
    assert results[0].address_text == "1000 Test Avenue, Bronx, NY, 10465"


HTML_WITH_ADDITIONAL_PROPERTY_PRICE = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Apartment",
  "name": "Co-op in Riverdale",
  "url": "https://streeteasy.com/building/riverdale-coop-bronx/3c",
  "address": {
    "streetAddress": "123 Riverdale Avenue",
    "addressLocality": "Riverdale",
    "addressRegion": "NY",
    "postalCode": "10463"
  },
  "additionalProperty": [
    {"@type": "PropertyValue", "name": "Price", "value": "$590,000"},
    {"@type": "PropertyValue", "name": "Building Type", "value": "CO_OP"}
  ],
  "image": [
    {"@type": "ImageObject", "url": "https://img.example/1.webp", "contentUrl": "https://img.example/1-copy.webp"}
  ],
  "numberOfBedrooms": "2",
  "numberOfBathroomsTotal": "1"
}
</script></head><body></body></html>
"""


HTML_WITH_FALLBACK_RESULTS = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "item": {
        "@type": "Apartment",
        "name": "Doorman apartment in Riverdale",
        "url": "https://streeteasy.com/building/riverdale-doorman-bronx/8a",
        "description": "Full-service doorman building in Riverdale.",
        "address": {
          "streetAddress": "500 Riverdale Avenue",
          "addressLocality": "Bronx",
          "addressRegion": "NY",
          "postalCode": "10463"
        },
        "offers": {"@type": "Offer", "price": "425000"},
        "numberOfBedrooms": "1",
        "numberOfBathroomsTotal": "1"
      }
    },
    {
      "@type": "ListItem",
      "position": 2,
      "item": {
        "@type": "Apartment",
        "name": "Nearby building",
        "url": "https://streeteasy.com/building/the-arches-nyc/4b",
        "description": "New development in Mott Haven.",
        "address": {
          "streetAddress": "224 East 135th Street",
          "addressLocality": "Bronx",
          "addressRegion": "NY",
          "postalCode": "10451"
        },
        "offers": {"@type": "Offer", "price": "510000"},
        "numberOfBedrooms": "2",
        "numberOfBathroomsTotal": "2"
      }
    },
    {
      "@type": "ListItem",
      "position": 3,
      "item": {
        "@type": "Apartment",
        "name": "Exact address match",
        "url": "https://streeteasy.com/building/225-east-134-street/3a",
        "description": "Boutique building near Third Avenue.",
        "address": {
          "streetAddress": "225 East 134th Street",
          "addressLocality": "Bronx",
          "addressRegion": "NY",
          "postalCode": "10454"
        },
        "offers": {"@type": "Offer", "price": "615000"},
        "numberOfBedrooms": "2",
        "numberOfBathroomsTotal": "2"
      }
    }
  ]
}
</script></head><body></body></html>
"""


async def test_search_parses_additional_property_price_and_image_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(
            200,
            text=HTML_WITH_ADDITIONAL_PROPERTY_PRICE,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client._client, "get", fake_get)
    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            locations=("Bronx",),
            limit=3,
        ),
    )

    assert len(results) == 1
    assert results[0].external_listing_id == "3c"
    assert results[0].price == 590000
    assert results[0].image_urls == ("https://img.example/1.webp",)


async def test_search_raises_when_streeteasy_returns_block_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        text = (
            "<html><title>Access to this page has been denied</title>"
            "<meta name='description' content='px-captcha'></html>"
        )
        return httpx.Response(200, text=text, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)

    with pytest.raises(StreetEasyBlockedError):
        await client.search(
            source=_source(),
            query=ListingSearchQuery(
                search_type=ListingSearchType.SALE,
                locations=("Bronx",),
                limit=3,
            ),
        )


async def test_search_raises_block_error_on_403_block_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        text = (
            "<html><title>Access to this page has been denied</title>"
            "<meta name='description' content='px-captcha'></html>"
        )
        return httpx.Response(403, text=text, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)

    with pytest.raises(StreetEasyBlockedError):
        await client.search(
            source=_source(),
            query=ListingSearchQuery(
                search_type=ListingSearchType.SALE,
                locations=("Bronx",),
                limit=3,
            ),
        )


def test_build_search_url_adds_known_keyword_filters() -> None:
    query = ListingSearchQuery(
        search_type=ListingSearchType.SALE,
        locations=("Bronx",),
        keywords=("co-op", "doorman", "parking"),
        min_price=Decimal("250000"),
        max_price=Decimal("700000"),
        min_beds=Decimal("2"),
        limit=3,
    )

    url = _build_search_url("https://streeteasy.com", query)

    assert url == (
        "https://streeteasy.com/for-sale/bronx/"
        "type:P1%7Camenities:doorman,parking%7Cprice:250000-700000%7Cbeds%3E=2"
    )


def test_build_search_url_uses_nyc_fallback_for_keyword_only_search() -> None:
    query = ListingSearchQuery(
        search_type=ListingSearchType.SALE,
        keywords=("doorman",),
        limit=3,
    )

    url = _build_search_url("https://streeteasy.com", query)

    assert url == "https://streeteasy.com/for-sale/nyc/amenities:doorman"


def test_build_search_url_uses_quick_search_for_address_only_queries() -> None:
    query = ListingSearchQuery(
        search_type=ListingSearchType.SALE,
        addresses=("225 East 134th Street",),
        limit=3,
    )

    url = _build_search_url("https://streeteasy.com", query)

    assert url == "https://streeteasy.com/search?search=225+East+134th+Street"


async def test_search_uses_keyword_only_query_without_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()
    requested_url = ""

    async def fake_get(url: str) -> httpx.Response:
        nonlocal requested_url
        requested_url = url
        return httpx.Response(200, text=HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)
    await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            keywords=("doorman",),
            limit=3,
        ),
    )

    assert requested_url == "https://streeteasy.com/for-sale/nyc/amenities:doorman"


async def test_search_falls_back_to_broader_location_search_when_keyword_route_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()
    requested_urls: list[str] = []

    async def fake_get(url: str) -> httpx.Response:
        requested_urls.append(url)
        if len(requested_urls) == 1:
            text = (
                "<html><title>Access to this page has been denied</title>"
                "<meta name='description' content='px-captcha'></html>"
            )
            return httpx.Response(403, text=text, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text=HTML_WITH_FALLBACK_RESULTS,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client._client, "get", fake_get)

    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            locations=("Bronx",),
            keywords=("doorman",),
            limit=3,
        ),
    )

    assert len(results) == 3
    assert [result.external_listing_id for result in results] == ["8a", "4b", "3a"]
    assert requested_urls == [
        "https://streeteasy.com/for-sale/bronx/amenities:doorman",
        "https://streeteasy.com/for-sale/bronx",
    ]


async def test_search_falls_back_to_broader_nyc_search_when_address_route_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()
    requested_urls: list[str] = []

    async def fake_get(url: str) -> httpx.Response:
        requested_urls.append(url)
        if len(requested_urls) == 1:
            text = (
                "<html><title>Access to this page has been denied</title>"
                "<meta name='description' content='px-captcha'></html>"
            )
            return httpx.Response(403, text=text, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text=HTML_WITH_FALLBACK_RESULTS,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client._client, "get", fake_get)

    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            addresses=("225 East 134th Street",),
            limit=3,
        ),
    )

    assert len(results) == 1
    assert results[0].external_listing_id == "3a"
    assert requested_urls == [
        "https://streeteasy.com/search?search=225+East+134th+Street",
        "https://streeteasy.com/for-sale/nyc",
    ]


async def test_search_softly_reranks_successful_address_results_without_dropping_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(
            200,
            text=HTML_WITH_FALLBACK_RESULTS,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client._client, "get", fake_get)

    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            addresses=("225 East 134th Street",),
            limit=3,
        ),
    )

    assert len(results) == 3
    assert results[0].external_listing_id == "3a"


async def test_search_keeps_successful_keyword_results_when_no_strong_local_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreetEasyListingSearchClient()

    async def fake_get(url: str) -> httpx.Response:
        return httpx.Response(200, text=HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", fake_get)

    results = await client.search(
        source=_source(),
        query=ListingSearchQuery(
            search_type=ListingSearchType.SALE,
            locations=("Bronx",),
            keywords=("doorman",),
            limit=3,
        ),
    )

    assert len(results) == 1
    assert results[0].external_listing_id == "1"
