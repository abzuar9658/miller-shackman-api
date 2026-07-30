import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.application.ports.listing_search import (
    ListingSearchClient,
    ListingSearchQuery,
    ListingSearchType,
)
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.services.listing_snapshot_matching import select_matching_snapshots
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    ApprovedOutboundListingContext,
    ApprovedOutboundListingMatch,
)
from app.domain.common.ids import WorkspaceId
from app.domain.leads import CanonicalLeadRecord, LeadType
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingSource,
)

STREETEASY_HOST = "streeteasy.com"
MAX_CACHE_CANDIDATES = 200
LOCATION_PREFERENCE_KEYS = ("location", "preferred_location", "neighborhood")
ADDRESS_PREFERENCE_KEYS = ("address", "preferred_address")
KEYWORD_PREFERENCE_KEYS = ("query", "keywords")
BEDROOM_PREFERENCE_KEYS = ("beds", "bedrooms")


async def maybe_enrich_outbound_lead_context(
    *,
    lead: CanonicalLeadRecord,
    lead_context: ApprovedOutboundLeadContext,
    now: datetime,
    enrichment_enabled: bool,
    cache_ttl: timedelta,
    max_results: int,
    source_repository: ListingSourceRepository | None,
    snapshot_repository: ListingSnapshotRepository | None,
    listing_search_client: ListingSearchClient | None,
) -> ApprovedOutboundLeadContext:
    if (
        not enrichment_enabled
        or source_repository is None
        or snapshot_repository is None
        or max_results <= 0
    ):
        return lead_context

    source = await _find_streeteasy_source(source_repository, lead.workspace_id)
    if source is None:
        return lead_context

    query = _build_listing_search_query(
        lead=lead,
        lead_context=lead_context,
        max_results=max_results,
    )
    if query is None:
        return lead_context

    live_matches = await _try_live_search(
        query=query,
        source=source,
        listing_search_client=listing_search_client,
    )
    if live_matches:
        matched_live_snapshots = select_matching_snapshots(
            live_matches,
            query=query,
            now=now,
            cache_ttl=cache_ttl,
            max_results=max_results,
        )
        if not matched_live_snapshots:
            matched_live_snapshots = live_matches[:max_results]

        saved_matches = await _persist_live_matches(
            lead=lead,
            source=source,
            snapshots=matched_live_snapshots,
            snapshot_repository=snapshot_repository,
            now=now,
            cache_ttl=cache_ttl,
        )
        matches = select_matching_snapshots(
            saved_matches,
            query=query,
            now=now,
            cache_ttl=cache_ttl,
            max_results=max_results,
        )
        if not matches:
            matches = saved_matches[:max_results]

        return replace(
            lead_context,
            listing_context=_listing_context_from_snapshots(
                source=source,
                query=query,
                snapshots=matches,
                listing_context_source="live",
            ),
        )

    cached_matches = await _fetch_cached_matches(
        workspace_id=lead.workspace_id,
        source=source,
        query=query,
        now=now,
        cache_ttl=cache_ttl,
        max_results=max_results,
        snapshot_repository=snapshot_repository,
    )
    if cached_matches:
        return replace(
            lead_context,
            listing_context=_listing_context_from_snapshots(
                source=source,
                query=query,
                snapshots=cached_matches,
                listing_context_source="cache",
            ),
        )

    return lead_context


async def _try_live_search(
    *,
    query: ListingSearchQuery,
    source: ListingSource,
    listing_search_client: ListingSearchClient | None,
) -> tuple[CanonicalListingSnapshot, ...]:
    if listing_search_client is None:
        return ()
    try:
        return await listing_search_client.search(source=source, query=query)
    except Exception:
        return ()


async def _fetch_cached_matches(
    *,
    workspace_id: WorkspaceId,
    source: ListingSource,
    query: ListingSearchQuery,
    now: datetime,
    cache_ttl: timedelta,
    max_results: int,
    snapshot_repository: ListingSnapshotRepository,
) -> tuple[CanonicalListingSnapshot, ...]:
    candidates = await snapshot_repository.list_current_for_source(
        workspace_id,
        source.source_id,
        limit=MAX_CACHE_CANDIDATES,
    )
    return select_matching_snapshots(
        candidates,
        query=query,
        now=now,
        cache_ttl=cache_ttl,
        max_results=max_results,
    )


async def _find_streeteasy_source(
    source_repository: ListingSourceRepository,
    workspace_id: WorkspaceId,
) -> ListingSource | None:
    sources = await source_repository.list_for_workspace(workspace_id)
    for source in sources:
        if not source.enabled or source.terms_reviewed_at is None or source.data_use_policy is None:
            continue
        if STREETEASY_HOST in source.base_url:
            return source
    return None


def _build_listing_search_query(
    *,
    lead: CanonicalLeadRecord,
    lead_context: ApprovedOutboundLeadContext,
    max_results: int,
) -> ListingSearchQuery | None:
    preferences = lead_context.extracted_preferences
    locations = _preference_values(preferences, LOCATION_PREFERENCE_KEYS)
    addresses = _preference_values(preferences, ADDRESS_PREFERENCE_KEYS)
    keywords = _preference_values(preferences, KEYWORD_PREFERENCE_KEYS)
    min_beds = _parse_decimal_preference(preferences, BEDROOM_PREFERENCE_KEYS)
    min_price, max_price = _price_range_from_preferences(
        preferences,
        lead.latest_property_price_band,
    )

    if not locations and not addresses and not keywords:
        return None
    if lead.lead_type == LeadType.SELLER and not addresses:
        return None

    return ListingSearchQuery(
        search_type=_search_type_for_lead(lead, preferences),
        locations=locations,
        addresses=addresses,
        keywords=keywords,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        limit=max_results,
    )


def _search_type_for_lead(
    lead: CanonicalLeadRecord,
    preferences: Mapping[str, str],
) -> ListingSearchType:
    raw = str(preferences.get("search_type", "")).strip().lower()
    if raw == ListingSearchType.RENT.value:
        return ListingSearchType.RENT
    if raw == ListingSearchType.SALE.value:
        return ListingSearchType.SALE
    if lead.lead_source.lower().find("rent") >= 0:
        return ListingSearchType.RENT
    return ListingSearchType.SALE


def _preference_values(
    preferences: Mapping[str, str],
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        raw = preferences.get(key)
        if raw is None:
            continue
        for value in str(raw).split(","):
            normalized = value.strip()
            if normalized:
                values.append(normalized)
    return tuple(dict.fromkeys(values))


def _parse_decimal_preference(
    preferences: Mapping[str, str],
    keys: tuple[str, ...],
) -> Decimal | None:
    for raw in _preference_values(preferences, keys):
        digits = re.sub(r"[^0-9.]", "", raw)
        if not digits:
            continue
        try:
            return Decimal(digits)
        except InvalidOperation:
            continue
    return None


def _price_range_from_preferences(
    preferences: Mapping[str, str],
    fallback_band: str | None,
) -> tuple[Decimal | None, Decimal | None]:
    explicit_min = _single_decimal(preferences.get("min_price"))
    explicit_max = _single_decimal(preferences.get("max_price"))
    if explicit_min is not None or explicit_max is not None:
        return explicit_min, explicit_max
    price_band = str(preferences.get("price_band", "")).strip() or fallback_band
    return _parse_price_band(price_band)


def _single_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    digits = re.sub(r"[^0-9.]", "", str(raw))
    if not digits:
        return None
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def _parse_price_band(raw: str | None) -> tuple[Decimal | None, Decimal | None]:
    if raw is None:
        return None, None
    value = raw.strip().lower().replace("$", "")
    if not value:
        return None, None
    aliases = {
        "under_500k": (None, Decimal("500000")),
        "500k_to_1m": (Decimal("500000"), Decimal("1000000")),
        "1m_to_2m": (Decimal("1000000"), Decimal("2000000")),
        "2m_plus": (Decimal("2000000"), None),
    }
    if value in aliases:
        return aliases[value]
    match = re.fullmatch(r"([0-9.]+)(k|m)?\s*(?:-|to)\s*([0-9.]+)(k|m)?", value)
    if match is not None:
        return _scaled_decimal(match.group(1), match.group(2)), _scaled_decimal(
            match.group(3),
            match.group(4),
        )
    return None, None


def _scaled_decimal(number: str, suffix: str | None) -> Decimal | None:
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None
    if suffix == "k":
        return value * Decimal("1000")
    if suffix == "m":
        return value * Decimal("1000000")
    return value


async def _persist_live_matches(
    *,
    lead: CanonicalLeadRecord,
    source: ListingSource,
    snapshots: tuple[CanonicalListingSnapshot, ...],
    snapshot_repository: ListingSnapshotRepository,
    now: datetime,
    cache_ttl: timedelta,
) -> tuple[CanonicalListingSnapshot, ...]:
    saved_matches: list[CanonicalListingSnapshot] = []
    for snapshot in snapshots:
        persisted = await snapshot_repository.save(
            replace(
                snapshot,
                snapshot_id=uuid4(),
                workspace_id=lead.workspace_id,
                source_id=source.source_id,
                scraped_at=now,
                created_at=now,
                updated_at=now,
                valid_until=now + cache_ttl,
            )
        )
        await snapshot_repository.mark_other_versions_not_current(
            lead.workspace_id,
            source.source_id,
            persisted.external_listing_id,
            persisted.snapshot_id,
        )
        saved_matches.append(persisted)
    return tuple(saved_matches)


def _listing_context_from_snapshots(
    *,
    source: ListingSource,
    query: ListingSearchQuery,
    snapshots: tuple[CanonicalListingSnapshot, ...],
    listing_context_source: str,
) -> ApprovedOutboundListingContext:
    return ApprovedOutboundListingContext(
        source_name=source.name,
        search_summary=_search_summary(query),
        result_count=len(snapshots),
        matches=tuple(
            _listing_match_from_snapshot(snapshot) for snapshot in snapshots[: query.limit]
        ),
        source=listing_context_source,
    )


def _search_summary(query: ListingSearchQuery) -> str:
    parts = [query.search_type.value]
    if query.locations:
        parts.append(f"in {', '.join(query.locations)}")
    if query.addresses:
        parts.append(f"near {', '.join(query.addresses)}")
    if query.max_price is not None:
        parts.append(f"up to {_format_currency(query.max_price)}")
    if query.min_beds is not None:
        parts.append(f"with {_format_decimal(query.min_beds)}+ beds")
    return " ".join(parts)


def _listing_match_from_snapshot(
    snapshot: CanonicalListingSnapshot,
) -> ApprovedOutboundListingMatch:
    return ApprovedOutboundListingMatch(
        title=snapshot.title,
        address_text=snapshot.address_text,
        neighborhood=snapshot.neighborhood,
        price_text=_format_currency(snapshot.price),
        beds_text=_format_count(snapshot.beds, "bd"),
        baths_text=_format_count(snapshot.baths, "ba"),
        property_type=snapshot.property_type,
        source_url=snapshot.source_url,
        scraped_at=snapshot.scraped_at.isoformat(),
    )


def _format_currency(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"${int(value):,}"


def _format_count(value: Decimal | None, suffix: str) -> str | None:
    if value is None:
        return None
    normalized = _format_decimal(value)
    return f"{normalized} {suffix}"


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return text[:-2] if text.endswith(".0") else text.rstrip("0").rstrip(".")
