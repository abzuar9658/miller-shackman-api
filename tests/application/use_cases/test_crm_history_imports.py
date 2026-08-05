import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.crm_history_imports import CrmHistoryImportJobRepository
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CrmConversationEventRepository,
    LeadRepository,
)
from app.application.use_cases.crm_history_imports import (
    CrmHistoryImportMutationStatus,
    CrmHistoryImportReasonCode,
    complete_crm_history_import_upload,
    create_crm_history_import,
    create_extension_crm_history_import,
    crm_history_export_batch_fingerprint,
    ingest_crm_history_events,
    promote_crm_history_import,
)
from app.domain.crm_history_imports import (
    CrmHistoryImportDirection,
    CrmHistoryImportEventPayload,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    CrmHistoryImportSource,
)
from app.domain.identity import (
    AuthAuditEventType,
    AuthenticatedActor,
    AuthenticatedExtensionDevice,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases._crm_history_import_fakes import (
    FakeAuthAuditLogRepository,
    FakeCrmConversationEventRepository,
    FakeCrmHistoryImportEventRepository,
    FakeCrmHistoryImportJobRepository,
    FakeLeadRepository,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("a0000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("a0000000-0000-0000-0000-000000000002")
ACTOR_ID = UUID("a0000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("a0000000-0000-0000-0000-000000000004")


async def test_create_requires_flag_permission_and_stores_only_token_hash() -> None:
    jobs = FakeCrmHistoryImportJobRepository()
    leads = FakeLeadRepository((_lead(),))
    disabled = await create_crm_history_import(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        enabled=False,
        lead_repository=cast(LeadRepository, leads),
        job_repository=jobs,
        now=NOW,
    )
    denied = await create_crm_history_import(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        enabled=True,
        lead_repository=cast(LeadRepository, leads),
        job_repository=jobs,
        now=NOW,
    )
    created = await create_crm_history_import(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        enabled=True,
        lead_repository=cast(LeadRepository, leads),
        job_repository=jobs,
        now=NOW,
        token_factory=lambda: "scoped-token",
    )

    assert disabled.reasons == (CrmHistoryImportReasonCode.FEATURE_DISABLED.value,)
    assert denied.status is CrmHistoryImportMutationStatus.REJECTED
    assert created.upload_token == "scoped-token"
    assert created.job is not None
    assert created.job.upload_token_hash == hashlib.sha256(b"scoped-token").hexdigest()
    assert "scoped-token" not in created.job.upload_token_hash


async def test_extension_create_allows_unassigned_agent_and_is_batch_idempotent() -> None:
    jobs = FakeCrmHistoryImportJobRepository()
    audit = FakeAuthAuditLogRepository()
    payloads = (
        CrmHistoryImportEventPayload(
            fingerprint="client-fingerprint",
            activity_type="text",
            direction=CrmHistoryImportDirection.INBOUND,
            occurred_at=NOW,
            content="Interested",
        ),
    )
    batch_fingerprint = crm_history_export_batch_fingerprint(payloads)
    leads = cast(LeadRepository, FakeLeadRepository((_lead(),)))

    first = await create_extension_crm_history_import(
        extension_device=AuthenticatedExtensionDevice(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            device_id=OTHER_WORKSPACE_ID,
        ),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        batch_fingerprint=batch_fingerprint,
        enabled=True,
        lead_repository=leads,
        job_repository=cast(CrmHistoryImportJobRepository, jobs),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
        token_factory=lambda: "extension-token",
    )
    repeated = await create_extension_crm_history_import(
        extension_device=AuthenticatedExtensionDevice(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            device_id=OTHER_WORKSPACE_ID,
        ),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        batch_fingerprint=batch_fingerprint,
        enabled=True,
        lead_repository=leads,
        job_repository=cast(CrmHistoryImportJobRepository, jobs),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
        token_factory=lambda: "extension-token",
    )

    assert first.status is CrmHistoryImportMutationStatus.CREATED
    assert repeated.status is CrmHistoryImportMutationStatus.DUPLICATE
    assert repeated.job == first.job
    assert first.job is not None
    assert first.job.source is CrmHistoryImportSource.EXTENSION
    assert first.job.source_device_id == OTHER_WORKSPACE_ID
    assert audit.logs[0].event_type is AuthAuditEventType.CRM_HISTORY_EXTENSION_EXPORT_REQUESTED
    assert len(audit.logs) == 2
    assert audit.logs[1].event_details["request_status"] == "duplicate"

    assert first.job is not None
    await jobs.save(replace(first.job, status=CrmHistoryImportJobStatus.CANCELLED))
    retried = await create_extension_crm_history_import(
        extension_device=AuthenticatedExtensionDevice(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            device_id=OTHER_WORKSPACE_ID,
        ),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        batch_fingerprint=batch_fingerprint,
        enabled=True,
        lead_repository=leads,
        job_repository=cast(CrmHistoryImportJobRepository, jobs),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
        token_factory=lambda: "replacement-token",
    )
    assert retried.status is CrmHistoryImportMutationStatus.CREATED
    assert retried.job is not None
    assert retried.job.import_job_id != first.job.import_job_id


async def test_ingest_is_scoped_deduplicated_and_has_no_promotion_side_effects() -> None:
    jobs, staged, canonical, audit, job, token = await _created_dependencies()
    payload = CrmHistoryImportEventPayload(
        external_activity_id="activity-1",
        fingerprint="fingerprint-1",
        activity_type="Text",
        occurred_at=NOW - timedelta(days=1),
        content="Historical message",
    )

    wrong_workspace = await ingest_crm_history_events(
        workspace_id=OTHER_WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        payloads=(payload,),
        job_repository=jobs,
        event_repository=staged,
        now=NOW,
    )
    wrong_token = await ingest_crm_history_events(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token="wrong",
        payloads=(payload,),
        job_repository=jobs,
        event_repository=staged,
        now=NOW,
    )
    accepted = await ingest_crm_history_events(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        payloads=(payload, payload),
        job_repository=jobs,
        event_repository=staged,
        now=NOW,
    )

    assert wrong_workspace.reasons == (CrmHistoryImportReasonCode.JOB_NOT_FOUND.value,)
    assert wrong_token.reasons == (CrmHistoryImportReasonCode.TOKEN_INVALID.value,)
    assert accepted.accepted_count == 1
    assert accepted.duplicate_count == 1
    assert canonical.events == {}
    assert len(audit.logs) == 1


async def test_complete_claimed_job_promotes_only_canonical_crm_events() -> None:
    jobs, staged, canonical, audit, job, token = await _created_dependencies()
    await ingest_crm_history_events(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        payloads=(
            CrmHistoryImportEventPayload(
                fingerprint="fingerprint-2",
                activity_type="Note",
                occurred_at=NOW,
                details={"source": "extension"},
            ),
        ),
        job_repository=jobs,
        event_repository=staged,
        now=NOW,
    )
    completed_upload = await complete_crm_history_import_upload(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        job_repository=jobs,
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
    )
    repeated_upload = await complete_crm_history_import_upload(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        job_repository=jobs,
        now=NOW,
    )
    claimed = await jobs.claim_ready(now=NOW, limit=10)
    promoted = await promote_crm_history_import(
        job=claimed[0],
        job_repository=jobs,
        event_repository=staged,
        conversation_event_repository=cast(CrmConversationEventRepository, canonical),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
    )

    assert completed_upload.status is CrmHistoryImportMutationStatus.READY
    assert repeated_upload.status is CrmHistoryImportMutationStatus.READY
    assert promoted.status.value == "completed"
    assert promoted.promoted_count == 1
    assert next(iter(canonical.events.values())).crm_activity_id == (
        "extension-fingerprint:fingerprint-2"
    )
    assert len(audit.logs) == 3


async def test_promotion_preserves_extension_event_types_and_nullable_direction() -> None:
    jobs, staged, canonical, audit, job, token = await _created_dependencies()
    payloads = (
        CrmHistoryImportEventPayload(
            fingerprint="text-fingerprint",
            external_activity_id="text-1",
            activity_type="text",
            direction=CrmHistoryImportDirection.INBOUND,
            occurred_at=NOW - timedelta(days=3),
            content="Inbound text",
            actor_name="Lead",
            details={"source": "extension", "direction_basis": "lead_link"},
        ),
        CrmHistoryImportEventPayload(
            fingerprint="email-fingerprint",
            external_activity_id="email-1",
            activity_type="email",
            direction=CrmHistoryImportDirection.OUTBOUND,
            occurred_at=NOW - timedelta(days=2),
            content="Email body",
            actor_name="Agent One",
            details={"source": "extension", "subject": "Follow-up"},
        ),
        CrmHistoryImportEventPayload(
            fingerprint="inquiry-fingerprint",
            external_activity_id="inquiry-1",
            activity_type="Property Inquiry",
            occurred_at=NOW - timedelta(days=1),
            content="Property inquiry details",
            details={"source": "extension", "direction_basis": "event"},
        ),
    )
    result = await ingest_crm_history_events(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        payloads=payloads,
        job_repository=jobs,
        event_repository=staged,
        now=NOW,
    )
    assert result.accepted_count == 3

    await complete_crm_history_import_upload(
        workspace_id=WORKSPACE_ID,
        import_job_id=job.import_job_id,
        upload_token=token,
        job_repository=jobs,
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
    )
    claimed = await jobs.claim_ready(now=NOW, limit=10)
    promoted = await promote_crm_history_import(
        job=claimed[0],
        job_repository=jobs,
        event_repository=staged,
        conversation_event_repository=cast(CrmConversationEventRepository, canonical),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
    )

    assert promoted.status is CrmHistoryImportJobStatus.COMPLETED
    assert promoted.promoted_count == 3
    events = sorted(canonical.events.values(), key=lambda event: event.occurred_at)
    assert [event.activity_type for event in events] == ["text", "email", "Property Inquiry"]
    assert [event.direction.value if event.direction else None for event in events] == [
        "inbound",
        "outbound",
        None,
    ]
    assert events[1].details["subject"] == "Follow-up"


async def _created_dependencies() -> tuple[
    FakeCrmHistoryImportJobRepository,
    FakeCrmHistoryImportEventRepository,
    FakeCrmConversationEventRepository,
    FakeAuthAuditLogRepository,
    CrmHistoryImportJob,
    str,
]:
    jobs = FakeCrmHistoryImportJobRepository()
    staged = FakeCrmHistoryImportEventRepository()
    canonical = FakeCrmConversationEventRepository()
    audit = FakeAuthAuditLogRepository()
    result = await create_crm_history_import(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        enabled=True,
        lead_repository=cast(LeadRepository, FakeLeadRepository((_lead(),))),
        job_repository=cast(CrmHistoryImportJobRepository, jobs),
        audit_log_repository=cast(AuthAuditLogRepository, audit),
        now=NOW,
        token_factory=lambda: "scoped-token",
    )
    assert result.job is not None
    assert result.upload_token is not None
    return jobs, staged, canonical, audit, result.job, result.upload_token


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("a0000000-0000-0000-0000-000000000005"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="fub-lead-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
    )