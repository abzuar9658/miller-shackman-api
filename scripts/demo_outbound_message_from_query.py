"""Draft outbound SMS/email from a lead query using the real outbound draft flow.

Usage:
    uv run python scripts/demo_outbound_message_from_query.py
    uv run python scripts/demo_outbound_message_from_query.py --mode live
    uv run python scripts/demo_outbound_message_from_query.py --show-prompt
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.listing_context_enrichment import (
    maybe_enrich_outbound_lead_context,
)
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundConversationItem,
    ApprovedOutboundLeadContext,
    build_listing_relevance_brief,
    draft_outbound_message,
)
from app.core.config import get_settings
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord, CRMProvider, LeadType
from app.domain.listing_sources import ListingSource, ListingSourceType
from app.infrastructure.providers import build_listing_search_client, build_llm_client

DEFAULT_QUERY = "interested in available apartments for rent in manhattan"


class _RecordingLLMClient:
    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return await self._inner.complete(request)


class _StubLLMClient:
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        match = re.search(r"Approved context: (.+)$", request.prompt)
        payload = json.loads(match.group(1)) if match else {}
        channel = str(payload.get("channel", "")).strip().lower()
        subject = "Quick follow-up on your question" if channel == "email" else None
        text = json.dumps(
            {
                "body": (
                    "Thanks for the question — your assigned agent can confirm "
                    "the property details "
                    "and send the most current info if you'd like."
                ),
                "subject": subject,
                "confidence": 0.91,
                "personalization_notes": ["Used property-specific follow-up context."],
                "safety_flags": [],
            }
        )
        return LLMResult(
            text=text,
            model="stub",
            prompt_version=request.prompt_version,
            latency_ms=1,
        )


class _SingleSourceRepository:
    def __init__(self, source: ListingSource) -> None:
        self._source = source

    async def list_for_workspace(self, workspace_id: object) -> tuple[ListingSource, ...]:
        return (self._source,) if self._source.workspace_id == workspace_id else ()


class _MemorySnapshotRepository:
    def __init__(self) -> None:
        self._snapshots: list[object] = []

    async def list_current_for_source(
        self,
        workspace_id: object,
        source_id: object,
        *,
        limit: int = 100,
    ) -> tuple[object, ...]:
        matches = [
            item
            for item in self._snapshots
            if item.workspace_id == workspace_id and item.source_id == source_id and item.is_current
        ]
        return tuple(matches[:limit])

    async def save(self, snapshot: object) -> object:
        self._snapshots.append(snapshot)
        return snapshot

    async def mark_other_versions_not_current(
        self,
        workspace_id: object,
        source_id: object,
        external_listing_id: str,
        except_snapshot_id: object,
    ) -> None:
        _ = (workspace_id, source_id, external_listing_id, except_snapshot_id)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Draft outbound SMS/email from a single lead query."
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Lead message or question to simulate.",
    )
    parser.add_argument(
        "--mode",
        choices=("live", "stub"),
        default="stub",
        help="Use the configured OpenRouter client or a local stub response.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the exact LLM prompt for each channel.",
    )
    return parser.parse_args(argv)


def _extract_preferences(query: str) -> dict[str, str]:
    """Parse a simple lead request into structured preferences.

    Handles two common shapes:
    - "interested in 420 East 72nd Street #2E..." -> address
    - "interested in available apartments for rent in Manhattan" -> broad search criteria
    """
    preferences: dict[str, str] = {}
    match = re.search(r"interested in\s+(.+?)(?:[.?!]|$)", query, flags=re.IGNORECASE)
    tail = match.group(1).strip() if match else query.strip()

    lower = tail.lower()
    if "rent" in lower or "for rent" in lower or "rental" in lower:
        preferences["search_type"] = "rent"
    elif "sale" in lower or "for sale" in lower or "buy" in lower:
        preferences["search_type"] = "sale"

    for borough in ("manhattan", "brooklyn", "queens", "bronx", "staten island"):
        if borough in lower:
            preferences["location"] = borough.title()
            break

    max_price = _extract_max_price(lower)
    if max_price is not None:
        preferences["max_price"] = max_price

    min_beds = _extract_min_beds(lower)
    if min_beds is not None:
        preferences["beds"] = min_beds

    if not preferences.get("location") and re.search(r"^\d+\s+", tail):
        preferences["address"] = tail

    if not preferences:
        preferences["keywords"] = tail

    return preferences


def _extract_max_price(text: str) -> str | None:
    match = re.search(
        r"(?:under|below|less than|max(?:imum)?(?: of)?|up to)\s*\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*([km])?",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return _scaled_number_text(match.group(1), match.group(2))


def _extract_min_beds(text: str) -> str | None:
    match = re.search(
        r"(?:at least\s+|minimum\s+|with\s+)?([0-9]+(?:\.[0-9]+)?)\s*\+?\s*"
        r"(?:bed|beds|bedroom|bedrooms|br)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1)


def _scaled_number_text(number: str, suffix: str | None) -> str | None:
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None

    multiplier = Decimal("1")
    if suffix is not None and suffix.lower() == "k":
        multiplier = Decimal("1000")
    elif suffix is not None and suffix.lower() == "m":
        multiplier = Decimal("1000000")

    scaled = (value * multiplier).to_integral_value()
    return str(int(scaled))


def _broad_search_summaries(preferences: dict[str, str]) -> tuple[str, str]:
    search_type = preferences.get("search_type", "listing")
    location = preferences.get("location")
    beds = preferences.get("beds")
    has_budget = "max_price" in preferences

    if search_type == "rent":
        search_label = "rental options"
    elif search_type == "sale":
        search_label = "homes for sale"
    else:
        search_label = "listing options"
    target = search_label if location is None else f"{search_label} in {location}"
    if beds is not None:
        target = f"{target} with at least {beds} bedrooms"
    if has_budget:
        target = f"{target} within the lead's stated budget"

    return (
        f"Lead is looking for {target}.",
        f"Recent memory: lead is searching for {target}.",
    )


def _build_lead(now: datetime) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="demo-lead",
        facts_derived_at=now,
        source_payload_version="demo:v1",
        lead_type=LeadType.BUYER,
        lead_source="StreetEasy inquiry",
        lead_stage="active_nurture",
        latest_property_context_present=True,
    )


async def _main() -> int:
    args = parse_args()
    settings = get_settings()
    now = datetime.now(UTC)
    lead = _build_lead(now)
    preferences = _extract_preferences(args.query)
    is_broad_search = bool(preferences.get("location") or preferences.get("search_type"))
    broad_conversation_summary, broad_memory_summary = _broad_search_summaries(preferences)
    lead_context = ApprovedOutboundLeadContext(
        conversation_summary=(
            broad_conversation_summary
            if is_broad_search
            else "Lead asked a property-specific follow-up question that may require "
            "agent confirmation."
        ),
        conversation_memory_summary=(
            broad_memory_summary
            if is_broad_search
            else "Recent memory: lead is evaluating a specific listing and asked for "
            "a feature confirmation."
        ),
        latest_lead_request=args.query,
        extracted_preferences=preferences,
        recent_conversation_items=(
            ApprovedOutboundConversationItem(
                occurred_at=now.isoformat(),
                title="Inbound message",
                content=args.query,
                direction="inbound",
                channel="email",
                actor_name="lead",
            ),
        ),
    )
    source = ListingSource(
        source_id=uuid4(),
        workspace_id=lead.workspace_id,
        name="StreetEasy",
        source_type=ListingSourceType.WEBSITE,
        base_url=settings.streeteasy_base_url,
        created_at=now,
        updated_at=now,
        enabled=True,
        terms_reviewed_at=now,
        data_use_policy="Reviewed for optional enrichment.",
    )
    listing_search_client = build_listing_search_client(settings) if args.mode == "live" else None
    lead_context = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=lead_context,
        now=now,
        enrichment_enabled=args.mode == "live",
        cache_ttl=timedelta(minutes=settings.listing_context_enrichment_cache_ttl_minutes),
        max_results=settings.listing_context_enrichment_max_results,
        source_repository=_SingleSourceRepository(source),
        snapshot_repository=_MemorySnapshotRepository(),
        listing_search_client=listing_search_client,
    )
    llm = _RecordingLLMClient(
        build_llm_client(settings) if args.mode == "live" else _StubLLMClient()
    )
    print(f"Query: {args.query}")
    print(f"Parsed preferences: {preferences}")
    if lead_context.listing_context is not None:
        brief = build_listing_relevance_brief(lead_context.listing_context)
        print(f"Listing brief: {brief.safe_talking_point}")
    else:
        print("Listing brief: none (no StreetEasy enrichment found)")
    for channel in (ContactChannel.SMS, ContactChannel.EMAIL):
        result = await draft_outbound_message(
            lead=lead,
            channel=channel,
            campaign_goal=(
                "Follow up on active property interest and hand off to an agent when needed."
            ),
            brokerage_name="Miller Schackman",
            assigned_agent_name="Assigned Agent",
            lead_context=lead_context,
            llm_client=llm,
            model=settings.openrouter_model if args.mode == "live" else None,
        )
        print(f"\n=== {channel.value.upper()} ===")
        print(f"status: {result.status}")
        if result.reasons:
            print(f"reasons: {', '.join(reason.value for reason in result.reasons)}")
        if result.safety_flags:
            print(f"safety_flags: {', '.join(result.safety_flags)}")
        if result.subject:
            print(f"subject: {result.subject}")
        print(f"body: {result.body}")
        if args.show_prompt:
            print("prompt:")
            print(llm.requests[-1].prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
