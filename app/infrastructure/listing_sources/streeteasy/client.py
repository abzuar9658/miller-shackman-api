import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import quote, quote_plus, urlparse
from uuid import uuid4

import httpx

from app.application.ports.listing_search import (
    ListingSearchQuery,
    ListingSearchType,
)
from app.application.services.listing_snapshot_matching import (
    rank_matching_snapshots,
    rerank_live_response_snapshots,
)
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingSnapshotStatus,
    ListingSource,
)

JSON_LD_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

PROPERTY_TYPE_CODES = {
    "condo": "D1",
    "condominium": "D1",
    "co-op": "P1",
    "coop": "P1",
    "co op": "P1",
}

AMENITY_CODES = {
    "central ac": "central_ac",
    "dishwasher": "dishwasher",
    "doorman": "doorman",
    "elevator": "elevator",
    "fireplace": "fireplace",
    "gym": "gym",
    "laundry": "laundry",
    "parking": "parking",
    "pool": "pool",
    "smoke free": "smoke_free",
    "storage": "storage",
    "washer dryer": "washer_dryer",
    "washer/dryer": "washer_dryer",
    "washer_dryer": "washer_dryer",
}


class StreetEasyBlockedError(RuntimeError):
    pass


class StreetEasyListingSearchClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        user_agent: str = "Mozilla/5.0 (compatible; MillerSchackmanBot/0.1)",
    ) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def search(
        self,
        *,
        source: ListingSource,
        query: ListingSearchQuery,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        if not query.locations and not query.addresses and not query.keywords:
            return ()
        return await self._run_search_request(source=source, query=query)

    async def _run_search_request(
        self,
        *,
        source: ListingSource,
        query: ListingSearchQuery,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        search_url = _build_search_url(source.base_url, query)
        response = await self._client.get(search_url)
        if _is_block_page(response.text):
            fallback_query = _block_fallback_query(query)
            if fallback_query is not None:
                fallback_url = _build_search_url(source.base_url, fallback_query)
                fallback_response = await self._client.get(fallback_url)
                if _is_block_page(fallback_response.text):
                    raise StreetEasyBlockedError("StreetEasy blocked listing search")
                fallback_response.raise_for_status()
                fallback_results = _parse_search_results_html(
                    html=fallback_response.text,
                    source=source,
                    query=fallback_query,
                )
                ranked_results = rank_matching_snapshots(
                    fallback_results,
                    query=query,
                    max_results=fallback_query.limit,
                )
                return rerank_live_response_snapshots(
                    ranked_results,
                    query=query,
                    max_results=query.limit,
                )
            raise StreetEasyBlockedError("StreetEasy blocked listing search")
        response.raise_for_status()
        results = _parse_search_results_html(
            html=response.text,
            source=source,
            query=query,
        )
        return rerank_live_response_snapshots(
            results,
            query=query,
            max_results=query.limit,
        )


def _build_search_url(base_url: str, query: ListingSearchQuery) -> str:
    if _should_use_quick_search(query):
        return _build_quick_search_url(base_url, query.addresses[0])

    kind = "for-rent" if query.search_type == ListingSearchType.RENT else "for-sale"
    location = _slugify(query.locations[0]) if query.locations else "nyc"
    location = location or "nyc"
    filters: list[str] = []
    property_type_codes = _property_type_filters(query.keywords)
    if property_type_codes:
        filters.append(f"type:{','.join(property_type_codes)}")
    amenity_codes = _amenity_filters(query.keywords)
    if amenity_codes:
        filters.append(f"amenities:{','.join(amenity_codes)}")
    if query.min_price is not None or query.max_price is not None:
        min_price = "" if query.min_price is None else str(int(query.min_price))
        max_price = "" if query.max_price is None else str(int(query.max_price))
        filters.append(f"price:{min_price}-{max_price}")
    if query.min_beds is not None:
        beds_text = _filter_number_text(query.min_beds)
        filters.append(f"beds>={beds_text}")
    path = f"/{kind}/{location}"
    if filters:
        encoded_filters = quote("|".join(filters), safe=":,=-")
        path = f"{path}/{encoded_filters}"
    return f"{base_url.rstrip('/')}{path}"


def _should_use_quick_search(query: ListingSearchQuery) -> bool:
    return bool(
        query.addresses
        and not query.locations
        and query.min_price is None
        and query.max_price is None
        and query.min_beds is None
        and not _property_type_filters(query.keywords)
        and not _amenity_filters(query.keywords)
    )


def _block_fallback_query(query: ListingSearchQuery) -> ListingSearchQuery | None:
    if not query.addresses and not query.keywords:
        return None
    fallback_limit = max(query.limit * 10, 30)
    return ListingSearchQuery(
        search_type=query.search_type,
        locations=query.locations,
        min_price=query.min_price,
        max_price=query.max_price,
        min_beds=query.min_beds,
        limit=fallback_limit,
    )


def _build_quick_search_url(base_url: str, address: str) -> str:
    return f"{base_url.rstrip('/')}/search?search={quote_plus(address)}"


def _property_type_filters(keywords: tuple[str, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for keyword in keywords:
        code = PROPERTY_TYPE_CODES.get(keyword.strip().lower())
        if code is not None and code not in codes:
            codes.append(code)
    return tuple(codes)


def _amenity_filters(keywords: tuple[str, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for keyword in keywords:
        code = AMENITY_CODES.get(keyword.strip().lower())
        if code is not None and code not in codes:
            codes.append(code)
    return tuple(codes)


def _slugify(value: str) -> str:
    slug = value.strip().lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _filter_number_text(value: Decimal | int | float) -> str:
    parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    integral = parsed.to_integral_value()
    if parsed == integral:
        return str(int(integral))
    return format(parsed.normalize(), "f").rstrip("0").rstrip(".")




def _is_block_page(html: str) -> bool:
    lowered = html.lower()
    return "access to this page has been denied" in lowered or "px-captcha" in lowered


def _parse_search_results_html(
    *,
    html: str,
    source: ListingSource,
    query: ListingSearchQuery,
) -> tuple[CanonicalListingSnapshot, ...]:
    objects = _json_ld_objects(html)
    scraped_at = datetime.now(UTC)
    matches: list[CanonicalListingSnapshot] = []
    for item in _item_list_entries(objects):
        snapshot = _snapshot_from_item(item, source=source, scraped_at=scraped_at)
        if snapshot is None:
            continue
        matches.append(snapshot)
        if len(matches) >= query.limit:
            break
    if matches:
        return tuple(matches)

    for item in objects:
        snapshot = _snapshot_from_item(item, source=source, scraped_at=scraped_at)
        if snapshot is None:
            continue
        matches.append(snapshot)
        if len(matches) >= query.limit:
            break
    return tuple(matches)


def _json_ld_objects(html: str) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    for blob in JSON_LD_PATTERN.findall(html):
        try:
            parsed = json.loads(unescape(blob.strip()))
        except json.JSONDecodeError:
            continue
        objects.extend(_flatten_json_ld(parsed))
    return objects


def _flatten_json_ld(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        dict_objects = [value]
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                dict_objects.extend(_flatten_json_ld(item))
        return dict_objects
    if isinstance(value, list):
        list_objects: list[dict[str, object]] = []
        for item in value:
            list_objects.extend(_flatten_json_ld(item))
        return list_objects
    return []


def _item_list_entries(objects: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for obj in objects:
        if str(obj.get("@type", "")).lower() != "itemlist":
            continue
        raw_entries = obj.get("itemListElement")
        if not isinstance(raw_entries, list):
            continue
        for entry in raw_entries:
            if isinstance(entry, dict):
                item = entry.get("item")
                entries.append(item if isinstance(item, dict) else entry)
    return entries


def _snapshot_from_item(
    item: dict[str, object],
    *,
    source: ListingSource,
    scraped_at: datetime,
) -> CanonicalListingSnapshot | None:
    source_url = _extract_url(item)
    if source_url is None:
        return None
    external_listing_id = _extract_listing_id(source_url)
    if external_listing_id is None:
        return None
    address_text, city, state, postal_code = _extract_address(item)
    payload_hash = hashlib.sha256(
        json.dumps(item, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return CanonicalListingSnapshot(
        snapshot_id=uuid4(),
        workspace_id=source.workspace_id,
        source_id=source.source_id,
        external_listing_id=external_listing_id,
        source_url=source_url,
        source_payload_hash=payload_hash,
        scraped_at=scraped_at,
        created_at=scraped_at,
        updated_at=scraped_at,
        title=_text(item.get("name")) or _text(item.get("headline")),
        address_text=address_text,
        city=city,
        state=state,
        postal_code=postal_code,
        neighborhood=_extract_neighborhood(item, address_text),
        price=_extract_price(item),
        beds=_extract_decimal(item, ("numberOfBedrooms", "numberOfRooms")),
        baths=_extract_decimal(item, ("numberOfBathroomsTotal", "numberOfBathrooms")),
        property_type=_extract_property_type(item),
        status=ListingSnapshotStatus.ACTIVE,
        description=_text(item.get("description")),
        image_urls=_extract_images(item),
        source_payload=item,
    )


def _extract_url(item: dict[str, object]) -> str | None:
    raw = item.get("url") or item.get("mainEntityOfPage")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        value = raw.get("@id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_listing_id(source_url: str | None) -> str | None:
    if source_url is None or not str(source_url).strip():
        return None
    text = source_url.decode("utf-8") if isinstance(source_url, bytes) else source_url
    path = urlparse(text).path.strip("/")
    if not path:
        return None
    match = re.search(r"([0-9]{5,})", path)
    if match is not None:
        return match.group(1)
    return path.split("/")[-1]


def _extract_address(
    item: dict[str, object],
) -> tuple[str | None, str | None, str | None, str | None]:
    raw = item.get("address")
    if isinstance(raw, str):
        return raw.strip(), None, None, None
    if not isinstance(raw, dict):
        return None, None, None, None
    street = _text(raw.get("streetAddress"))
    city = _text(raw.get("addressLocality"))
    state = _text(raw.get("addressRegion"))
    postal_code = _text(raw.get("postalCode"))
    address_text = ", ".join(part for part in (street, city, state, postal_code) if part) or None
    return address_text, city, state, postal_code


def _extract_neighborhood(item: dict[str, object], address_text: str | None) -> str | None:
    area = item.get("areaServed")
    if isinstance(area, dict):
        return _text(area.get("name"))
    if isinstance(area, str):
        return area.strip()
    if address_text is not None:
        parts = [part.strip() for part in address_text.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[1]
    return None


def _extract_price(item: dict[str, object]) -> Decimal | None:
    offers = item.get("offers")
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                price = _single_decimal(offer.get("price"))
                if price is not None:
                    return price
    elif isinstance(offers, dict):
        price = _single_decimal(offers.get("price"))
        if price is not None:
            return price

    additional = item.get("additionalProperty")
    if isinstance(additional, list):
        for prop in additional:
            if not isinstance(prop, dict):
                continue
            if str(prop.get("name", "")).strip().lower() == "price":
                price = _single_decimal(prop.get("value"))
                if price is not None:
                    return price
    return None


def _extract_decimal(item: dict[str, object], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _single_decimal(item.get(key))
        if value is not None:
            return value
    return None


def _single_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    text = re.sub(r"[^0-9.]", "", str(raw))
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _extract_property_type(item: dict[str, object]) -> str | None:
    raw_type = item.get("@type")
    if isinstance(raw_type, str) and raw_type.strip():
        return raw_type.strip().lower()
    return _text(item.get("additionalType"))


def _extract_images(item: dict[str, object]) -> tuple[str, ...]:
    raw = item.get("image")
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    if isinstance(raw, list):
        urls: list[str] = []
        for value in raw:
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
            elif isinstance(value, dict):
                for key in ("url", "contentUrl"):
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        urls.append(candidate.strip())
                        break
        return tuple(urls)
    return ()


def _text(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    return normalized or None