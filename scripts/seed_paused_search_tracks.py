"""Create and publish the six standard paused-search tracks.

Run from ``miller-schackman-api`` after migrations and PostgreSQL are available:

    uv run python scripts/seed_paused_search_tracks.py \
        --workspace-id <workspace-uuid> --user-id <brokerage-admin-uuid>

The user must be an active brokerage admin (or platform super admin) in the
workspace. Existing track keys are left untouched, making this safe to rerun.
The script uses step template profiles rather than creating approved template
rows; the profiles are stored with each step and produce distinct email/SMS
drafting instructions at execution time.
"""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackConfigInput,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackStepInput,
    create_draft_paused_search_track,
    publish_paused_search_track_version,
    update_draft_paused_search_track,
)
from app.application.use_cases.preview_paused_search_track import (
    PausedSearchTrackPreviewStatus,
    preview_paused_search_track_version,
)
from app.core.config import get_settings
from app.core.database import enable_postgres_service_access
from app.domain.campaigns import (
    PausedSearchChannelSequence,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchReplyPolicy,
    PausedSearchStepAction,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrackMode,
    PausedSearchTrackStepPhase,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import LeadPausedSearchProfile
from app.domain.outbound_drafting import (
    DormantCallToAction,
    DormantGreeting,
    DormantListingContextBehavior,
    DormantMessageLength,
    DormantMessageStyle,
    DormantMessageTone,
    DormantPersonalizationField,
    DormantSignOff,
    DormantStepTemplateProfile,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminAuditLogRepository,
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.template_repository import PostgresTemplateRepository


@dataclass(frozen=True)
class TrackDefinition:
    key: str
    display_name: str
    selection_guidance: str
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    reactivation_window_days: int
    default_pause_duration_days: int
    reply_policy: PausedSearchReplyPolicy
    maintenance_interval_days: int
    listing_context: DormantListingContextBehavior
    custom_instruction: str
    maintenance_email_purpose: str
    maintenance_sms_purpose: str
    reactivation_email_purpose: str
    reactivation_sms_purpose: str


# fmt: off
# ruff: noqa: E501
TRACK_DEFINITIONS = (
    TrackDefinition(
        "specific_property_only",
        "Specific property only",
        (
            "Lead paused after expressing interest in one specific property and is not "
            "asking for a showing, agent call, or verified property advice now; do not "
            "broaden the search. Current requests for property help require human handoff."
        ),
        PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
        7,
        60,
        PausedSearchReplyPolicy.END,
        30,
        DormantListingContextBehavior.NEVER,
        (
            "Reference only the original property context when it is approved and fresh; "
            "never suggest alternatives."
        ),
        maintenance_email_purpose=(
            "Check in to see if they're still thinking about that specific property. "
            "Ask if their situation or interest has changed. Do not offer alternatives or broaden the search."
        ),
        maintenance_sms_purpose=(
            "Quick check: Are you still interested in that property, or have your plans changed?"
        ),
        reactivation_email_purpose=(
            "Ask specifically about that one property they were interested in. Mention it was "
            "a single property pause and ask if they're still thinking about it or if their "
            "situation has changed. Do not offer to broaden the search or suggest alternatives."
        ),
        reactivation_sms_purpose=(
            "Still interested in that specific property, or have your plans shifted?"
        ),
    ),
    TrackDefinition(
        "waiting_for_inventory",
        "Waiting for inventory",
        (
            "Lead paused because the available inventory did not fit and may want to "
            "revisit criteria later."
        ),
        PausedSearchFallbackTimingPolicy.USE_DEFAULT_PAUSE_DURATION,
        14,
        60,
        PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
        30,
        DormantListingContextBehavior.WHEN_AVAILABLE,
        (
            "Use only approved, fresh listing facts when present; never claim availability "
            "or pricing that is not verified."
        ),
        maintenance_email_purpose=(
            "Check in to see if they're still waiting for better inventory. "
            "Ask if anything has changed or if they'd like their agent to review what's currently available. "
            "Keep it low-pressure and administrative."
        ),
        maintenance_sms_purpose=(
            "Quick check-in: Still waiting for the right home, or would you like to see what's available now?"
        ),
        reactivation_email_purpose=(
            "Acknowledge they paused because available homes didn't fit what they were looking for. "
            "Ask if they'd be open to adjusting their criteria (location, price range, property type) "
            "or if they prefer to wait until better options come on the market. Offer to have their "
            "agent check what's currently available without making claims about inventory."
        ),
        reactivation_sms_purpose=(
            "Ready to restart your search? We can adjust criteria or keep waiting for the right fit. Let me know!"
        ),
    ),
    TrackDefinition(
        "renter_now_future_buyer",
        "Renter now, future buyer",
        (
            "Lead found a rental or is renting temporarily and may consider buying after "
            "the rental timeline changes."
        ),
        PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        30,
        90,
        PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
        60,
        DormantListingContextBehavior.GENERAL_CRITERIA_ONLY,
        (
            "Stay focused on timing and future planning; do not provide financing, tax, "
            "legal, or investment advice."
        ),
        maintenance_email_purpose=(
            "Check in to see how their rental situation is going. "
            "Ask if their timeline or plans for transitioning from renting to buying have changed. "
            "Keep it patient and future-focused."
        ),
        maintenance_sms_purpose=(
            "How's your rental going? Still thinking about buying in the future?"
        ),
        reactivation_email_purpose=(
            "Acknowledge they're renting for now but may want to buy in the future. Ask if their "
            "rental situation or timeline for buying has changed. Frame it as keeping the door open "
            "for when they're ready to make the move from renting to owning. Warm and patient tone."
        ),
        reactivation_sms_purpose=(
            "Ready to transition from renting to buying, or still on your current timeline?"
        ),
    ),
    TrackDefinition(
        "lease_expiration",
        "Lease expiration",
        (
            "Lead paused while waiting for a known lease expiration or move-out date "
            "before restarting the search."
        ),
        PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        60,
        90,
        PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
        60,
        DormantListingContextBehavior.GENERAL_CRITERIA_ONLY,
        (
            "Ask whether the lease date or moving plan changed; do not infer a date that "
            "the lead did not provide."
        ),
        maintenance_email_purpose=(
            "Check in to see if their lease end date or move-out timing has changed. "
            "Simple status check - no pressure."
        ),
        maintenance_sms_purpose=(
            "Quick check: Is your lease end date still the same?"
        ),
        reactivation_email_purpose=(
            "Reference their upcoming lease expiration and ask if that move-out date is still on track "
            "or if it changed. Frame the message around coordinating the home search with their lease "
            "end. Ask when they'd like to start looking so they can transition smoothly when the lease is up."
        ),
        reactivation_sms_purpose=(
            "Lease expiration approaching! Ready to coordinate your home search timing?"
        ),
    ),
    TrackDefinition(
        "recently_renewed_lease",
        "Recently renewed lease",
        (
            "Lead recently renewed a lease and wants the buying conversation deferred to "
            "the new timing boundary."
        ),
        PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        30,
        180,
        PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
        90,
        DormantListingContextBehavior.GENERAL_CRITERIA_ONLY,
        (
            "Treat the renewed lease date as customer-provided timing; ask before changing "
            "the timing anchor."
        ),
        maintenance_email_purpose=(
            "Check in to see if their renewed lease timeline is still the plan. "
            "Respectful check-in that honors their decision to extend the lease."
        ),
        maintenance_sms_purpose=(
            "Quick check: Is your renewed lease timeline still on track?"
        ),
        reactivation_email_purpose=(
            "Acknowledge they recently renewed their lease and pushed the home-buying timeline out. "
            "Ask if anything has changed—did they decide to break the lease early, or is the renewed "
            "lease end date still when they plan to buy? Respectful tone that honors their original decision "
            "to renew while checking if circumstances shifted."
        ),
        reactivation_sms_purpose=(
            "Renewed lease timeline approaching! Still planning to buy then, or did plans change?"
        ),
    ),
    TrackDefinition(
        "search_fit_reassessment",
        "Search fit reassessment",
        (
            "Lead paused because expectations, criteria, or timing did not fit and may "
            "need a human reassessment."
        ),
        PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
        14,
        60,
        PausedSearchReplyPolicy.END,
        30,
        DormantListingContextBehavior.GENERAL_CRITERIA_ONLY,
        (
            "Ask whether criteria changed and hand off advice, affordability, market, or "
            "strategy questions to the agent."
        ),
        maintenance_email_purpose=(
            "Check in to see if they've had time to think about their priorities. "
            "Low-pressure question about whether their criteria or expectations have shifted."
        ),
        maintenance_sms_purpose=(
            "Have you had a chance to rethink your search criteria?"
        ),
        reactivation_email_purpose=(
            "Acknowledge there was a mismatch between what they were looking for and what was realistic "
            "or available. Ask if they've had a chance to rethink their priorities—like location, budget, "
            "property type, or timeline. Make it clear their agent can help work through options if they "
            "want to adjust expectations or explore different approaches."
        ),
        reactivation_sms_purpose=(
            "Ready to revisit your search? Your agent can help work through options if priorities shifted."
        ),
    ),
)
# fmt: on


def _profile(
    *,
    channel: ContactChannel,
    phase: PausedSearchTrackStepPhase,
    listing_context: DormantListingContextBehavior,
    custom_instruction: str,
) -> DormantStepTemplateProfile:
    is_email = channel is ContactChannel.EMAIL
    is_maintenance = phase is PausedSearchTrackStepPhase.MAINTENANCE
    return DormantStepTemplateProfile(
        tone=DormantMessageTone.LOW_PRESSURE if is_maintenance else DormantMessageTone.WARM,
        style=(
            DormantMessageStyle.SHORT_CHECK_IN
            if is_maintenance
            else DormantMessageStyle.REENGAGEMENT_QUESTION
        ),
        length=DormantMessageLength.SHORT if is_email else DormantMessageLength.VERY_SHORT,
        call_to_action=(
            DormantCallToAction.ASK_IF_PLANS_CHANGED
            if is_maintenance
            else DormantCallToAction.INVITE_REPLY
        ),
        greeting=DormantGreeting.LEAD_FIRST_NAME if is_email else DormantGreeting.NONE,
        sign_off=DormantSignOff.BEST_BROKERAGE if is_email else DormantSignOff.NONE,
        listing_context=listing_context,
        personalization_fields=(
            DormantPersonalizationField.LEAD_FIRST_NAME,
            DormantPersonalizationField.TIMELINE,
            DormantPersonalizationField.RECENT_CONVERSATION,
        ),
        custom_instructions=custom_instruction,
    )


def _steps(definition: TrackDefinition) -> tuple[PausedSearchTrackStepInput, ...]:
    key = definition.key
    return (
        PausedSearchTrackStepInput(
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.EMAIL,
            delay_hours=0,
            message_goal=f"Maintenance email purpose: {definition.maintenance_email_purpose}",
            template_key=f"paused-search-{key}-maintenance-email-v1",
            max_attempts=1,
            timing_basis=PausedSearchTimingBasis.PREVIOUS_OCCURRENCE,
            max_occurrences=1,
            action=PausedSearchStepAction.SEND,
            template_profile=_profile(
                channel=ContactChannel.EMAIL,
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                listing_context=definition.listing_context,
                custom_instruction=definition.custom_instruction,
            ),
        ),
        PausedSearchTrackStepInput(
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.SMS,
            delay_hours=24,
            message_goal=f"Maintenance SMS purpose: {definition.maintenance_sms_purpose}",
            template_key=f"paused-search-{key}-maintenance-sms-v1",
            max_attempts=1,
            timing_basis=PausedSearchTimingBasis.PREVIOUS_OCCURRENCE,
            max_occurrences=1,
            action=PausedSearchStepAction.SEND,
            template_profile=_profile(
                channel=ContactChannel.SMS,
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                listing_context=definition.listing_context,
                custom_instruction=definition.custom_instruction,
            ),
        ),
        PausedSearchTrackStepInput(
            phase=PausedSearchTrackStepPhase.REACTIVATION,
            channel=ContactChannel.EMAIL,
            delay_hours=0,
            message_goal=(
                f"Reactivation email purpose: {definition.reactivation_email_purpose} "
                "Revisit the conversation only when the timing allows."
            ),
            template_key=f"paused-search-{key}-reactivation-email-v1",
            max_attempts=1,
            timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            max_occurrences=1,
            action=PausedSearchStepAction.SEND,
            template_profile=_profile(
                channel=ContactChannel.EMAIL,
                phase=PausedSearchTrackStepPhase.REACTIVATION,
                listing_context=definition.listing_context,
                custom_instruction=definition.custom_instruction,
            ),
        ),
        PausedSearchTrackStepInput(
            phase=PausedSearchTrackStepPhase.REACTIVATION,
            channel=ContactChannel.SMS,
            delay_hours=24,
            message_goal=(
                f"Reactivation SMS purpose: {definition.reactivation_sms_purpose} "
                "Invite a brief reply without pressure."
            ),
            template_key=f"paused-search-{key}-reactivation-sms-v1",
            max_attempts=1,
            timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            max_occurrences=1,
            action=PausedSearchStepAction.SEND,
            template_profile=_profile(
                channel=ContactChannel.SMS,
                phase=PausedSearchTrackStepPhase.REACTIVATION,
                listing_context=definition.listing_context,
                custom_instruction=definition.custom_instruction,
            ),
        ),
        PausedSearchTrackStepInput(
            phase=PausedSearchTrackStepPhase.REACTIVATION,
            channel=ContactChannel.EMAIL,
            delay_hours=120,
            message_goal=(
                f"Final reactivation email purpose: {definition.reactivation_email_purpose} "
                "Make one final low-pressure attempt before completing the track."
            ),
            template_key=f"paused-search-{key}-reactivation-final-email-v1",
            max_attempts=1,
            timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            max_occurrences=1,
            action=PausedSearchStepAction.SEND,
            template_profile=_profile(
                channel=ContactChannel.EMAIL,
                phase=PausedSearchTrackStepPhase.REACTIVATION,
                listing_context=definition.listing_context,
                custom_instruction=definition.custom_instruction,
            ),
        ),
    )


def _config(definition: TrackDefinition) -> PausedSearchTrackConfigInput:
    return PausedSearchTrackConfigInput(
        selection_guidance=definition.selection_guidance,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        fallback_timing_policy=definition.fallback_timing_policy,
        maintenance_interval_days=definition.maintenance_interval_days,
        reactivation_window_days=definition.reactivation_window_days,
        max_total_touches=5,
        default_pause_duration_days=definition.default_pause_duration_days,
        max_duration_days=730,
        terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
        track_mode=PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
        interim_contact_policy=PausedSearchInterimContactPolicy.REQUIRES_EXPLICIT_LEAD_PERMISSION,
        reply_policy=definition.reply_policy,
        channel_sequence=PausedSearchChannelSequence.SEQUENTIAL,
        max_cycles=1,
        max_ai_interactions=5,
        restart_delay_days=30,
        # Legacy fallback purposes - actual step-specific purposes are in message_goal
        email_writing_purpose=definition.reactivation_email_purpose,
        sms_writing_purpose=definition.reactivation_sms_purpose,
        steps=_steps(definition),
    )


def _preview_workflow(workspace_id: UUID, now: datetime) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=uuid4(),
        temporal_workflow_id=f"paused-search-seed-preview-{uuid4()}",
        workspace_id=workspace_id,
        campaign_enrollment_id=uuid4(),
        campaign_id=uuid4(),
        lead_id=uuid4(),
        state=WorkflowState.QUEUED,
        last_transition_at=now,
        state_version=0,
        created_at=now,
        updated_at=now,
    )


async def _load_actor(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> AuthenticatedActor:
    workspace = await PostgresWorkspaceRepository(session).get_by_id(workspace_id)
    user = await PostgresUserRepository(session).get_by_id(user_id)
    membership = await PostgresWorkspaceMembershipRepository(session).get_by_user_and_workspace(
        user_id, workspace_id
    )
    if workspace is None or user is None or membership is None:
        raise RuntimeError("workspace, user, or workspace membership was not found")
    if workspace.status is not WorkspaceStatus.ACTIVE:
        raise RuntimeError("workspace is not active")
    if user.status is not UserStatus.ACTIVE:
        raise RuntimeError("seed user is not active")
    if membership.status is not WorkspaceMembershipStatus.ACTIVE:
        raise RuntimeError("seed user membership is not active")
    if membership.role not in {
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN,
    }:
        raise RuntimeError("seed user must be a brokerage admin or platform super admin")
    return AuthenticatedActor(
        user_id=user.user_id,
        user_status=user.status,
        active_role=membership.role,
        active_workspace_id=workspace.workspace_id,
        active_workspace_status=workspace.status,
        active_membership_id=membership.membership_id,
        active_membership_status=membership.status,
    )


async def _seed_track(
    *,
    session: AsyncSession,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    definition: TrackDefinition,
    now: datetime,
    overwrite_draft: bool,
) -> str:
    repository = PostgresPausedSearchTrackAdminRepository(session)
    existing = await repository.get_track_by_key(workspace_id, definition.key)
    if existing is not None and not overwrite_draft:
        return f"SKIP {definition.key}: already exists ({existing.status.value})"

    audit_repository = PostgresPausedSearchTrackAdminAuditLogRepository(session)
    template_repository = PostgresTemplateRepository(session)
    event_bus = PostgresTransactionalEventBus(PostgresOutboxEventRepository(session))
    config = _config(definition)
    if existing is None:
        result = await create_draft_paused_search_track(
            actor=actor,
            workspace_id=workspace_id,
            track_key=definition.key,
            display_name=definition.display_name,
            config=config,
            repository=repository,
            audit_log_repository=audit_repository,
            template_repository=template_repository,
            now=now,
            event_bus=event_bus,
        )
    else:
        result = await update_draft_paused_search_track(
            actor=actor,
            workspace_id=workspace_id,
            track_id=existing.track_id,
            track_key=definition.key,
            display_name=definition.display_name,
            config=config,
            repository=repository,
            audit_log_repository=audit_repository,
            template_repository=template_repository,
            now=now,
            event_bus=event_bus,
        )
    if result.status is PausedSearchTrackDraftStatus.REJECTED or result.view is None:
        raise RuntimeError(f"{definition.key}: draft rejected: {result.reasons}")

    view = result.view
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        paused_search_track_key=definition.key,
        paused_search_track_version_id=view.version.track_version_id,
        reengagement_not_before=now + timedelta(days=definition.default_pause_duration_days),
    )
    preview = await preview_paused_search_track_version(
        actor=actor,
        track=view.track,
        version=view.version,
        steps=view.steps,
        profile=profile,
        workflow=_preview_workflow(workspace_id, now),
        timezone="UTC",
        now=now,
        templates={},
    )
    if (
        preview.status is not PausedSearchTrackPreviewStatus.READY
        or preview.preview_reference is None
    ):
        raise RuntimeError(f"{definition.key}: preview blocked: {preview.validation.findings}")

    published = await publish_paused_search_track_version(
        actor=actor,
        workspace_id=workspace_id,
        track_id=view.track.track_id,
        track_version_id=view.version.track_version_id,
        repository=repository,
        audit_log_repository=audit_repository,
        template_repository=template_repository,
        now=now,
        event_bus=event_bus,
        expected_version_number=view.version.version_number,
        preview_reference=preview.preview_reference,
        confirm_warnings=False,
    )
    if published.view is None:
        raise RuntimeError(f"{definition.key}: publish rejected: {published.reasons}")
    await session.commit()
    return (
        f"CREATED {definition.key}: track_id={published.view.track.track_id} "
        f"version_id={published.view.version.track_version_id} steps={len(published.view.steps)}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--overwrite-draft", action="store_true")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            actor = await _load_actor(session, args.workspace_id, args.user_id)
            now = datetime.now(UTC)
            for definition in TRACK_DEFINITIONS:
                try:
                    print(
                        await _seed_track(
                            session=session,
                            actor=actor,
                            workspace_id=args.workspace_id,
                            definition=definition,
                            now=now,
                            overwrite_draft=args.overwrite_draft,
                        )
                    )
                except Exception:
                    await session.rollback()
                    raise
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
