from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.application.ports.listing_search import ListingSearchQuery
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.use_cases.workspace_outbound_drafting import (
    OutboundDraftingPreviewStatus,
    preview_workspace_outbound_drafting,
)
from app.domain.identity import WorkspaceMembershipRole
from app.domain.listing_sources import CanonicalListingSnapshot, ListingSource, ListingSourceType
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig
from tests.application.use_cases.test_authentication import (
    MEMBERSHIP_ID,
    WORKSPACE_ID,
    _actor,
    _Dependencies,
    _membership,
    _workspace,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


class _FakePreviewLLMClient:
    def __init__(self) -> None:
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        if '"channel": "sms"' in request.prompt:
            payload = (
                '{"body":"SMS preview body","subject":null,'
                '"confidence":0.91,"personalization_notes":[],"safety_flags":[]}'
            )
        else:
            payload = (
                '{"body":"Email preview body","subject":"Preview subject",'
                '"confidence":0.91,"personalization_notes":[],"safety_flags":[]}'
            )
        return LLMResult(
            text=payload,
            model=request.model or "openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=10,
            usage_tokens=50,
        )


class _FakeListingSourceRepository:
    def __init__(self, source: ListingSource) -> None:
        self._source = source

    async def get_by_id(
        self, workspace_id: UUID, source_id: UUID
    ) -> ListingSource | None:
        if self._source.workspace_id == workspace_id and self._source.source_id == source_id:
            return self._source
        return None

    async def get_by_name(
        self, workspace_id: UUID, name: str
    ) -> ListingSource | None:
        if self._source.workspace_id == workspace_id and self._source.name == name:
            return self._source
        return None

    async def list_for_workspace(
        self, workspace_id: UUID
    ) -> tuple[ListingSource, ...]:
        return (self._source,) if workspace_id == self._source.workspace_id else ()

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        return (self._source,) if self._source.enabled else ()

    async def save(self, source: ListingSource) -> ListingSource:
        self._source = source
        return source


class _FakeListingSnapshotRepository:
    async def get_by_id(
        self, workspace_id: UUID, snapshot_id: UUID
    ) -> CanonicalListingSnapshot | None:
        return None

    async def get_current_by_external_id(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        return None

    async def list_current_for_source(
        self, workspace_id: UUID, source_id: UUID, *, limit: int = 100
    ) -> tuple[CanonicalListingSnapshot, ...]:
        return ()

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        return snapshot

    async def mark_other_versions_not_current(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
        except_snapshot_id: UUID,
    ) -> None:
        return None


class _FakeListingSearchClient:
    def __init__(self, snapshot: CanonicalListingSnapshot) -> None:
        self.snapshot = snapshot
        self.search_calls: list[ListingSearchQuery] = []

    async def search(
        self, *, source: ListingSource, query: ListingSearchQuery
    ) -> tuple[CanonicalListingSnapshot, ...]:
        self.search_calls.append(query)
        return (self.snapshot,)


def test_preview_workspace_outbound_drafting_uses_saved_config_and_live_search() -> None:
    deps = _Dependencies()
    llm_client = _FakePreviewLLMClient()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.memberships[MEMBERSHIP_ID] = _membership(role=WorkspaceMembershipRole.BROKERAGE_ADMIN)
    deps.workspace_outbound_drafting_configs[WORKSPACE_ID] = WorkspaceOutboundDraftingConfig(
        workspace_id=WORKSPACE_ID,
        revision=2,
        prompt_text=(
            "You are the brokerage's preview drafting assistant. Re-engage the lead "
            "safely and tee up an agent follow-up."
        ),
        sms_prompt_text="Saved SMS prompt text",
        sms_template="Hi {{agent_name}}",
        email_prompt_text="Saved email prompt text",
        email_template="Regards,\n{{brokerage_name}}",
        email_subject_template="{{message_subject}} | {{brokerage_name}}",
        enabled_extraction_fields=("location", "max_price", "search_type"),
    )
    source = ListingSource(
        source_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        created_at=NOW,
        updated_at=NOW,
        enabled=True,
    )
    live_snapshot = CanonicalListingSnapshot(
        snapshot_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source.source_id,
        external_listing_id="listing-1",
        source_url="https://streeteasy.com/building/example/1a",
        source_payload_hash="hash-1",
        scraped_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        neighborhood="Astoria",
        property_type="apartment",
        title="Astoria apartment",
    )
    listing_search_client = _FakeListingSearchClient(live_snapshot)

    result = _run(
        preview_workspace_outbound_drafting(
            actor=_actor(role=WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            query="Looking for 2 bedroom apartments for rent in Queens under $2k/month",
            agent_name="Taylor Agent",
            brokerage_name="Taylor Brokerage",
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            workspace_outbound_drafting_config_repository=deps.workspace_outbound_drafting_config_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            llm_client=llm_client,
            listing_source_repository=_FakeListingSourceRepository(source),
            listing_snapshot_repository=_FakeListingSnapshotRepository(),
            listing_search_client=listing_search_client,
            now=NOW,
        ),
    )

    assert result.status == OutboundDraftingPreviewStatus.PREVIEWED
    assert result.parsed_preferences is not None
    assert result.parsed_preferences["max_price"] == "2000"
    assert result.parsed_preferences["location"].startswith("Queens")
    assert "beds" not in result.parsed_preferences
    assert result.sms_preview is not None
    assert result.sms_preview.body == "Hi Taylor Agent\n\nSMS preview body"
    assert result.email_preview is not None
    assert result.email_preview.subject == "Preview subject | Taylor Brokerage"
    assert result.email_preview.body is not None
    assert result.email_preview.body == "Regards,\nTaylor Brokerage\n\nEmail preview body"
    assert result.sms_preview.prompt_version == "outbound_message_draft:v8:r2"
    assert len(llm_client.requests) == 2
    assert all(
        "You are the brokerage's preview drafting assistant." in request.prompt
        for request in llm_client.requests
    )


def _run(coroutine: Any) -> Any:
    import asyncio

    return asyncio.run(coroutine)
