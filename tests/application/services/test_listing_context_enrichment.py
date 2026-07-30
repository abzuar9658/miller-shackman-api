from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.ports.listing_search import ListingSearchQuery
from app.application.services.listing_context_enrichment import maybe_enrich_outbound_lead_context
from app.application.services.llm.outbound_message_drafting import ApprovedOutboundLeadContext
from app.domain.leads import CanonicalLeadRecord, CRMProvider, LeadType
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingSnapshotStatus,
    ListingSource,
    ListingSourceType,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


class FakeListingSourceRepository:
    def __init__(self, source: ListingSource | None) -> None:
        self.source = source

    async def get_by_id(self, workspace_id: UUID, source_id: UUID) -> ListingSource | None:
        if (
            self.source is not None
            and self.source.workspace_id == workspace_id
            and self.source.source_id == source_id
        ):
            return self.source
        return None

    async def get_by_name(self, workspace_id: UUID, name: str) -> ListingSource | None:
        if (
            self.source is not None
            and self.source.workspace_id == workspace_id
            and self.source.name == name
        ):
            return self.source
        return None

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[ListingSource, ...]:
        if self.source is None or self.source.workspace_id != workspace_id:
            return ()
        return (self.source,)

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        if self.source is None or not self.source.enabled:
            return ()
        return (self.source,)

    async def save(self, source: ListingSource) -> ListingSource:
        self.source = source
        return source


class FakeListingSnapshotRepository:
    def __init__(self, snapshots: tuple[CanonicalListingSnapshot, ...] = ()) -> None:
        self.snapshots = list(snapshots)
        self.saved: list[CanonicalListingSnapshot] = []

    async def get_by_id(
        self,
        workspace_id: UUID,
        snapshot_id: UUID,
    ) -> CanonicalListingSnapshot | None:
        for snapshot in self.snapshots:
            if snapshot.workspace_id == workspace_id and snapshot.snapshot_id == snapshot_id:
                return snapshot
        return None

    async def get_current_by_external_id(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        for snapshot in self.snapshots:
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.external_listing_id == external_listing_id
                and snapshot.is_current
            ):
                return snapshot
        return None

    async def list_current_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        filtered = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.workspace_id == workspace_id
            and snapshot.source_id == source_id
            and snapshot.is_current
        ]
        return tuple(filtered[:limit])

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        self.saved.append(snapshot)
        self.snapshots.append(snapshot)
        return snapshot

    async def mark_other_versions_not_current(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
        except_snapshot_id: UUID,
    ) -> None:
        for index, snapshot in enumerate(self.snapshots):
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.external_listing_id == external_listing_id
                and snapshot.snapshot_id != except_snapshot_id
            ):
                self.snapshots[index] = CanonicalListingSnapshot(
                    **{**snapshot.__dict__, "is_current": False}
                )


class FakeListingSearchClient:
    def __init__(
        self,
        snapshots: tuple[CanonicalListingSnapshot, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.error = error
        self.queries: list[ListingSearchQuery] = []

    async def search(
        self, *, source: ListingSource, query: ListingSearchQuery
    ) -> tuple[CanonicalListingSnapshot, ...]:
        _ = source
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.snapshots


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_type=LeadType.BUYER,
        latest_property_price_band="500k-750k",
    )


def _source(workspace_id: UUID) -> ListingSource:
    return ListingSource(
        source_id=uuid4(),
        workspace_id=workspace_id,
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        enabled=True,
        terms_reviewed_at=NOW,
        data_use_policy="Reviewed for optional enrichment.",
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(workspace_id: UUID, source_id: UUID) -> CanonicalListingSnapshot:
    return CanonicalListingSnapshot(
        snapshot_id=uuid4(),
        workspace_id=workspace_id,
        source_id=source_id,
        external_listing_id="2738-miles-1",
        source_url="https://streeteasy.com/building/2738-miles-avenue-bronx/1",
        source_payload_hash="hash-1",
        scraped_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        title="Single-family house in Throgs Neck",
        address_text="2738 Miles Avenue, Bronx, NY 10465",
        neighborhood="Bronx",
        price=Decimal("650000"),
        beds=Decimal("4"),
        baths=Decimal("1"),
        property_type="house",
        status=ListingSnapshotStatus.ACTIVE,
        is_current=True,
    )


async def test_uses_fresh_cached_listing_matches_when_available() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    snapshot = _snapshot(lead.workspace_id, source.source_id)

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=6),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=FakeListingSnapshotRepository((snapshot,)),
        listing_search_client=None,
    )

    assert enriched.listing_context is not None
    assert enriched.listing_context.source_name == "StreetEasy"
    assert enriched.listing_context.source == "cache"
    assert enriched.listing_context.matches[0].address_text == "2738 Miles Avenue, Bronx, NY 10465"


async def test_fetches_and_persists_listing_matches_when_cache_is_empty() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    snapshot = _snapshot(lead.workspace_id, source.source_id)
    snapshot_repository = FakeListingSnapshotRepository()
    client = FakeListingSearchClient((snapshot,))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=6),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=client,
    )

    assert len(client.queries) == 1
    assert len(snapshot_repository.saved) == 1
    assert enriched.listing_context is not None
    assert enriched.listing_context.source == "live"
    assert enriched.listing_context.matches[0].price_text == "$650,000"


async def test_skips_listing_enrichment_when_live_search_errors() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=6),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=FakeListingSnapshotRepository(),
        listing_search_client=FakeListingSearchClient(error=RuntimeError("blocked")),
    )

    assert enriched.listing_context is None


async def test_persists_only_locally_matched_live_snapshots() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    matching_snapshot = _snapshot(lead.workspace_id, source.source_id)
    non_matching_snapshot = CanonicalListingSnapshot(
        **{
            **matching_snapshot.__dict__,
            "snapshot_id": uuid4(),
            "external_listing_id": "other-1",
            "source_url": "https://streeteasy.com/building/other-bronx/1",
            "address_text": "10 Other Street, Queens, NY 11101",
            "neighborhood": "Queens",
            "price": Decimal("900000"),
            "beds": Decimal("1"),
        }
    )
    snapshot_repository = FakeListingSnapshotRepository()
    client = FakeListingSearchClient((non_matching_snapshot, matching_snapshot))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=6),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=client,
    )

    assert enriched.listing_context is not None
    assert len(snapshot_repository.saved) == 1
    assert snapshot_repository.saved[0].address_text == "2738 Miles Avenue, Bronx, NY 10465"


async def test_uses_soft_live_results_when_address_query_has_no_strict_match() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    fuzzy_snapshot = CanonicalListingSnapshot(
        **{
            **_snapshot(lead.workspace_id, source.source_id).__dict__,
            "snapshot_id": uuid4(),
            "external_listing_id": "fuzzy-1",
            "source_url": "https://streeteasy.com/building/the-arches-nyc/4b",
            "address_text": "224 East 135th Street, Bronx, NY 10451",
            "neighborhood": "Bronx",
            "price": None,
            "beds": None,
            "baths": None,
            "property_type": "apartmentcomplex",
        }
    )
    snapshot_repository = FakeListingSnapshotRepository()
    client = FakeListingSearchClient((fuzzy_snapshot,))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(
            extracted_preferences={"address": "225 East 134th Street"}
        ),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=6),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=client,
    )

    assert enriched.listing_context is not None
    assert len(snapshot_repository.saved) == 1
    assert snapshot_repository.saved[0].external_listing_id == "fuzzy-1"


async def test_prefers_live_search_over_cached_matches() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    cached_snapshot = _snapshot(lead.workspace_id, source.source_id)
    live_snapshot = CanonicalListingSnapshot(
        **{
            **cached_snapshot.__dict__,
            "snapshot_id": uuid4(),
            "external_listing_id": "live-1",
            "source_url": "https://streeteasy.com/building/live/1",
            "address_text": "1 Live Street, Bronx, NY 10465",
        }
    )
    snapshot_repository = FakeListingSnapshotRepository((cached_snapshot,))
    client = FakeListingSearchClient((live_snapshot,))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=1),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=client,
    )

    assert enriched.listing_context is not None
    assert enriched.listing_context.source == "live"
    assert len(enriched.listing_context.matches) == 1
    assert enriched.listing_context.matches[0].address_text == "1 Live Street, Bronx, NY 10465"
    assert len(snapshot_repository.saved) == 1
    assert snapshot_repository.saved[0].external_listing_id == "live-1"


async def test_falls_back_to_cached_matches_when_live_search_is_empty() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    cached_snapshot = _snapshot(lead.workspace_id, source.source_id)
    snapshot_repository = FakeListingSnapshotRepository((cached_snapshot,))
    client = FakeListingSearchClient(())

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=1),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=client,
    )

    assert enriched.listing_context is not None
    assert enriched.listing_context.source == "cache"
    assert enriched.listing_context.matches[0].address_text == "2738 Miles Avenue, Bronx, NY 10465"


async def test_falls_back_to_cached_matches_when_live_search_errors() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    cached_snapshot = _snapshot(lead.workspace_id, source.source_id)
    snapshot_repository = FakeListingSnapshotRepository((cached_snapshot,))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=1),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=FakeListingSearchClient(error=RuntimeError("blocked")),
    )

    assert enriched.listing_context is not None
    assert enriched.listing_context.source == "cache"
    assert enriched.listing_context.matches[0].address_text == "2738 Miles Avenue, Bronx, NY 10465"


async def test_does_not_use_stale_cached_matches_when_live_search_fails() -> None:
    lead = _lead()
    source = _source(lead.workspace_id)
    stale_snapshot = CanonicalListingSnapshot(
        **{
            **_snapshot(lead.workspace_id, source.source_id).__dict__,
            "snapshot_id": uuid4(),
            "scraped_at": NOW - timedelta(hours=2),
            "valid_until": NOW - timedelta(hours=1),
        }
    )
    snapshot_repository = FakeListingSnapshotRepository((stale_snapshot,))

    enriched = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=ApprovedOutboundLeadContext(extracted_preferences={"location": "Bronx"}),
        now=NOW,
        enrichment_enabled=True,
        cache_ttl=timedelta(hours=1),
        max_results=3,
        source_repository=FakeListingSourceRepository(source),
        snapshot_repository=snapshot_repository,
        listing_search_client=FakeListingSearchClient(error=RuntimeError("blocked")),
    )

    assert enriched.listing_context is None