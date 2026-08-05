import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4, uuid5

from app.application.ports.crm_history_imports import (
    CrmHistoryImportEventRepository,
    CrmHistoryImportJobRepository,
)
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CrmConversationEventRepository,
    LeadRepository,
)
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    canonical_crm_event_identity,
)
from app.domain.crm_history_imports import (
    CrmHistoryImportEventPayload,
    CrmHistoryImportEventStatus,
    CrmHistoryImportJob,
    CrmHistoryImportJobStatus,
    CrmHistoryImportSource,
    StagedCrmHistoryImportEvent,
)
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    AuthenticatedActor,
    AuthenticatedExtensionDevice,
    PermissionCapability,
    PermissionContext,
    evaluate_permission,
)
from app.domain.leads import CRMProvider

_PROMOTION_ID_NAMESPACE = UUID("7b73c6d2-7858-4b72-9e94-0b0be435d52b")
_RECEIVING_STATUSES = frozenset(
    {CrmHistoryImportJobStatus.PENDING, CrmHistoryImportJobStatus.RECEIVING}
)


class CrmHistoryImportReasonCode(StrEnum):
    FEATURE_DISABLED = "feature_disabled"
    LEAD_NOT_FOUND = "lead_not_found"
    UNSUPPORTED_CRM_PROVIDER = "unsupported_crm_provider"
    ACTIVE_JOB_EXISTS = "active_job_exists"
    JOB_NOT_FOUND = "job_not_found"
    TOKEN_INVALID = "token_invalid"
    TOKEN_EXPIRED = "token_expired"
    JOB_NOT_RECEIVING = "job_not_receiving"


class CrmHistoryImportMutationStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    ACCEPTED = "accepted"
    READY = "ready"
    REJECTED = "rejected"


class CrmHistoryImportReadStatus(StrEnum):
    FOUND = "found"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CrmHistoryImportCapabilityResult:
    enabled: bool
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CreateCrmHistoryImportResult:
    status: CrmHistoryImportMutationStatus
    job: CrmHistoryImportJob | None = None
    upload_token: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestCrmHistoryEventsResult:
    status: CrmHistoryImportMutationStatus
    job: CrmHistoryImportJob | None = None
    accepted_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrmHistoryImportJobResult:
    status: CrmHistoryImportMutationStatus | CrmHistoryImportReadStatus
    job: CrmHistoryImportJob | None = None
    reasons: tuple[str, ...] = ()


def evaluate_crm_history_import_capability(
    *, actor: AuthenticatedActor, enabled: bool
) -> CrmHistoryImportCapabilityResult:
    permission = evaluate_permission(actor, PermissionCapability.IMPORT_CRM_HISTORY)
    reasons: list[str] = []
    if not enabled:
        reasons.append(CrmHistoryImportReasonCode.FEATURE_DISABLED.value)
    reasons.extend(reason.value for reason in permission.reasons)
    return CrmHistoryImportCapabilityResult(
        enabled=enabled,
        allowed=enabled and permission.allowed,
        reasons=tuple(reasons),
    )


async def create_crm_history_import(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    lead_id: UUID,
    enabled: bool,
    lead_repository: LeadRepository,
    job_repository: CrmHistoryImportJobRepository,
    now: datetime,
    audit_log_repository: AuthAuditLogRepository | None = None,
    token_ttl: timedelta = timedelta(hours=24),
    token_factory: Callable[[], str] | None = None,
) -> CreateCrmHistoryImportResult:
    return await _create_crm_history_import(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        enabled=enabled,
        lead_repository=lead_repository,
        job_repository=job_repository,
        now=now,
        audit_log_repository=audit_log_repository,
        token_ttl=token_ttl,
        token_factory=token_factory,
        capability=PermissionCapability.IMPORT_CRM_HISTORY,
        require_assigned_lead=True,
        source=CrmHistoryImportSource.MANUAL,
    )


async def create_extension_crm_history_import(
    *,
    extension_device: AuthenticatedExtensionDevice,
    workspace_id: UUID,
    lead_id: UUID,
    batch_fingerprint: str,
    enabled: bool,
    lead_repository: LeadRepository,
    job_repository: CrmHistoryImportJobRepository,
    now: datetime,
    audit_log_repository: AuthAuditLogRepository | None = None,
    token_ttl: timedelta = timedelta(hours=24),
    token_factory: Callable[[], str] | None = None,
) -> CreateCrmHistoryImportResult:
    return await _create_crm_history_import(
        actor=extension_device.actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        enabled=enabled,
        lead_repository=lead_repository,
        job_repository=job_repository,
        now=now,
        audit_log_repository=audit_log_repository,
        token_ttl=token_ttl,
        token_factory=token_factory,
        capability=PermissionCapability.EXPORT_CRM_HISTORY_FROM_EXTENSION,
        require_assigned_lead=False,
        source=CrmHistoryImportSource.EXTENSION,
        batch_fingerprint=batch_fingerprint,
        source_device_id=extension_device.device_id,
    )


async def _create_crm_history_import(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    lead_id: UUID,
    enabled: bool,
    lead_repository: LeadRepository,
    job_repository: CrmHistoryImportJobRepository,
    now: datetime,
    audit_log_repository: AuthAuditLogRepository | None,
    token_ttl: timedelta,
    token_factory: Callable[[], str] | None,
    capability: PermissionCapability,
    require_assigned_lead: bool,
    source: CrmHistoryImportSource,
    batch_fingerprint: str | None = None,
    source_device_id: UUID | None = None,
) -> CreateCrmHistoryImportResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return _create_rejection(CrmHistoryImportReasonCode.LEAD_NOT_FOUND)
    permission = evaluate_permission(
        actor,
        capability,
        PermissionContext(
            acts_on_assigned_lead=(
                is_actor_assigned_to_lead(actor, lead) if require_assigned_lead else False
            )
        ),
    )
    if not enabled or not permission.allowed:
        reasons = ([] if enabled else [CrmHistoryImportReasonCode.FEATURE_DISABLED.value])
        reasons.extend(reason.value for reason in permission.reasons)
        return CreateCrmHistoryImportResult(
            status=CrmHistoryImportMutationStatus.REJECTED,
            reasons=tuple(reasons),
        )
    if lead.crm_provider is not CRMProvider.FOLLOW_UP_BOSS:
        return _create_rejection(CrmHistoryImportReasonCode.UNSUPPORTED_CRM_PROVIDER)
    if batch_fingerprint is not None:
        existing_batch = await job_repository.get_by_batch_fingerprint(
            workspace_id, lead_id, batch_fingerprint
        )
        if existing_batch is not None:
            await _append_audit(
                audit_log_repository,
                event_type=AuthAuditEventType.CRM_HISTORY_EXTENSION_EXPORT_REQUESTED,
                job=existing_batch,
                now=now,
                actor_user_id=actor.user_id,
                request_status=CrmHistoryImportMutationStatus.DUPLICATE,
            )
            return CreateCrmHistoryImportResult(
                status=CrmHistoryImportMutationStatus.DUPLICATE,
                job=existing_batch,
            )
    if await job_repository.get_active_for_lead(workspace_id, lead_id) is not None:
        return _create_rejection(CrmHistoryImportReasonCode.ACTIVE_JOB_EXISTS)

    upload_token = (token_factory or _new_upload_token)()
    job = CrmHistoryImportJob(
        import_job_id=uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        crm_lead_id=lead.crm_lead_id,
        requested_by_user_id=actor.user_id,
        status=CrmHistoryImportJobStatus.PENDING,
        upload_token_hash=_hash_upload_token(upload_token),
        token_expires_at=now + token_ttl,
        created_at=now,
        updated_at=now,
        source=source,
        batch_fingerprint=batch_fingerprint,
        source_device_id=source_device_id,
    )
    created = await job_repository.create(job)
    if created is None:
        if batch_fingerprint is not None:
            existing_batch = await job_repository.get_by_batch_fingerprint(
                workspace_id, lead_id, batch_fingerprint
            )
            if existing_batch is not None:
                await _append_audit(
                    audit_log_repository,
                    event_type=AuthAuditEventType.CRM_HISTORY_EXTENSION_EXPORT_REQUESTED,
                    job=existing_batch,
                    now=now,
                    actor_user_id=actor.user_id,
                    request_status=CrmHistoryImportMutationStatus.DUPLICATE,
                )
                return CreateCrmHistoryImportResult(
                    status=CrmHistoryImportMutationStatus.DUPLICATE,
                    job=existing_batch,
                )
        return _create_rejection(CrmHistoryImportReasonCode.ACTIVE_JOB_EXISTS)
    await _append_audit(
        audit_log_repository,
        event_type=(
            AuthAuditEventType.CRM_HISTORY_EXTENSION_EXPORT_REQUESTED
            if source is CrmHistoryImportSource.EXTENSION
            else AuthAuditEventType.CRM_HISTORY_IMPORT_JOB_REQUESTED
        ),
        job=created,
        now=now,
        actor_user_id=actor.user_id,
    )
    return CreateCrmHistoryImportResult(
        status=CrmHistoryImportMutationStatus.CREATED,
        job=created,
        upload_token=upload_token,
    )


async def ingest_crm_history_events(
    *,
    workspace_id: UUID,
    import_job_id: UUID,
    upload_token: str,
    payloads: tuple[CrmHistoryImportEventPayload, ...],
    job_repository: CrmHistoryImportJobRepository,
    event_repository: CrmHistoryImportEventRepository,
    now: datetime,
) -> IngestCrmHistoryEventsResult:
    job, rejection = await _authenticated_receiving_job(
        workspace_id=workspace_id,
        import_job_id=import_job_id,
        upload_token=upload_token,
        job_repository=job_repository,
        now=now,
    )
    if rejection is not None:
        return IngestCrmHistoryEventsResult(
            status=CrmHistoryImportMutationStatus.REJECTED,
            reasons=(rejection.value,),
        )
    assert job is not None
    staged = tuple(_stage_payload(job=job, payload=payload, now=now) for payload in payloads)
    inserted = await event_repository.insert_received(staged)
    accepted_count = len(inserted)
    duplicate_count = len(staged) - accepted_count
    updated_job = await job_repository.save(
        replace(
            job,
            status=CrmHistoryImportJobStatus.RECEIVING,
            received_count=job.received_count + accepted_count,
            duplicate_count=job.duplicate_count + duplicate_count,
            updated_at=now,
        )
    )
    return IngestCrmHistoryEventsResult(
        status=CrmHistoryImportMutationStatus.ACCEPTED,
        job=updated_job,
        accepted_count=accepted_count,
        duplicate_count=duplicate_count,
    )


async def complete_crm_history_import_upload(
    *,
    workspace_id: UUID,
    import_job_id: UUID,
    upload_token: str,
    job_repository: CrmHistoryImportJobRepository,
    now: datetime,
    audit_log_repository: AuthAuditLogRepository | None = None,
) -> CrmHistoryImportJobResult:
    existing_job = await job_repository.get_for_update(workspace_id, import_job_id)
    if existing_job is not None:
        if not _token_matches(existing_job, upload_token):
            existing_job = None
        elif existing_job.token_expires_at <= now:
            return CrmHistoryImportJobResult(
                status=CrmHistoryImportMutationStatus.REJECTED,
                reasons=(CrmHistoryImportReasonCode.TOKEN_EXPIRED.value,),
            )
        elif existing_job.status in {
            CrmHistoryImportJobStatus.READY,
            CrmHistoryImportJobStatus.RUNNING,
            CrmHistoryImportJobStatus.COMPLETED,
            CrmHistoryImportJobStatus.PARTIAL,
        }:
            return CrmHistoryImportJobResult(
                status=CrmHistoryImportMutationStatus.READY,
                job=existing_job,
            )
    job, rejection = await _authenticated_receiving_job(
        workspace_id=workspace_id,
        import_job_id=import_job_id,
        upload_token=upload_token,
        job_repository=job_repository,
        now=now,
    )
    if rejection is not None:
        return CrmHistoryImportJobResult(
            status=CrmHistoryImportMutationStatus.REJECTED,
            reasons=(rejection.value,),
        )
    assert job is not None
    ready = await job_repository.save(
        replace(
            job,
            status=CrmHistoryImportJobStatus.READY,
            upload_completed_at=now,
            updated_at=now,
        )
    )
    await _append_audit(
        audit_log_repository,
        event_type=AuthAuditEventType.CRM_HISTORY_IMPORT_UPLOAD_COMPLETED,
        job=ready,
        now=now,
        actor_user_id=None,
    )
    return CrmHistoryImportJobResult(status=CrmHistoryImportMutationStatus.READY, job=ready)


async def read_crm_history_import(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    import_job_id: UUID,
    job_repository: CrmHistoryImportJobRepository,
) -> CrmHistoryImportJobResult:
    permission = evaluate_permission(actor, PermissionCapability.IMPORT_CRM_HISTORY)
    if not permission.allowed:
        return CrmHistoryImportJobResult(
            status=CrmHistoryImportReadStatus.REJECTED,
            reasons=tuple(reason.value for reason in permission.reasons),
        )
    job = await job_repository.get_by_id(workspace_id, import_job_id)
    if job is None:
        return CrmHistoryImportJobResult(
            status=CrmHistoryImportReadStatus.REJECTED,
            reasons=(CrmHistoryImportReasonCode.JOB_NOT_FOUND.value,),
        )
    return CrmHistoryImportJobResult(status=CrmHistoryImportReadStatus.FOUND, job=job)


async def claim_ready_crm_history_imports(
    *, job_repository: CrmHistoryImportJobRepository, now: datetime, limit: int
) -> tuple[CrmHistoryImportJob, ...]:
    return await job_repository.claim_ready(now=now, limit=limit)


async def promote_crm_history_import(
    *,
    job: CrmHistoryImportJob,
    job_repository: CrmHistoryImportJobRepository,
    event_repository: CrmHistoryImportEventRepository,
    conversation_event_repository: CrmConversationEventRepository,
    now: datetime,
    audit_log_repository: AuthAuditLogRepository | None = None,
) -> CrmHistoryImportJob:
    staged_events = await event_repository.list_received(job.workspace_id, job.import_job_id)
    promoted_count = 0
    failure_count = 0
    for staged in staged_events:
        try:
            await conversation_event_repository.save(_canonical_event(staged, now=now))
        except Exception as error:
            failure_count += 1
            await event_repository.save(
                replace(
                    staged,
                    status=CrmHistoryImportEventStatus.REJECTED,
                    failure_reason=error.__class__.__name__[:255],
                )
            )
            continue
        promoted_count += 1
        await event_repository.save(
            replace(
                staged,
                status=CrmHistoryImportEventStatus.PROMOTED,
                promoted_at=now,
                failure_reason=None,
            )
        )

    final_status = CrmHistoryImportJobStatus.COMPLETED
    if failure_count and promoted_count:
        final_status = CrmHistoryImportJobStatus.PARTIAL
    elif failure_count:
        final_status = CrmHistoryImportJobStatus.FAILED
    completed = await job_repository.save(
        replace(
            job,
            status=final_status,
            promoted_count=job.promoted_count + promoted_count,
            rejected_count=job.rejected_count + failure_count,
            failure_count=job.failure_count + failure_count,
            completed_at=now,
            updated_at=now,
            failure_reason="event_promotion_failed" if failure_count else None,
        )
    )
    await _append_audit(
        audit_log_repository,
        event_type=(
            AuthAuditEventType.CRM_HISTORY_IMPORT_PROMOTION_FAILED
            if failure_count
            else AuthAuditEventType.CRM_HISTORY_IMPORT_PROMOTION_COMPLETED
        ),
        job=completed,
        now=now,
        actor_user_id=None,
    )
    return completed


def _new_upload_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_upload_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_matches(job: CrmHistoryImportJob, token: str) -> bool:
    return hmac.compare_digest(job.upload_token_hash, _hash_upload_token(token))


async def _authenticated_receiving_job(
    *,
    workspace_id: UUID,
    import_job_id: UUID,
    upload_token: str,
    job_repository: CrmHistoryImportJobRepository,
    now: datetime,
) -> tuple[CrmHistoryImportJob | None, CrmHistoryImportReasonCode | None]:
    job = await job_repository.get_for_update(workspace_id, import_job_id)
    if job is None:
        return None, CrmHistoryImportReasonCode.JOB_NOT_FOUND
    if not _token_matches(job, upload_token):
        return None, CrmHistoryImportReasonCode.TOKEN_INVALID
    if job.token_expires_at <= now:
        return None, CrmHistoryImportReasonCode.TOKEN_EXPIRED
    if job.status not in _RECEIVING_STATUSES:
        return None, CrmHistoryImportReasonCode.JOB_NOT_RECEIVING
    return job, None


def _stage_payload(
    *, job: CrmHistoryImportJob, payload: CrmHistoryImportEventPayload, now: datetime
) -> StagedCrmHistoryImportEvent:
    return StagedCrmHistoryImportEvent(
        import_event_id=uuid4(),
        workspace_id=job.workspace_id,
        import_job_id=job.import_job_id,
        lead_id=job.lead_id,
        fingerprint=payload.fingerprint,
        external_activity_id=payload.external_activity_id,
        activity_type=payload.activity_type,
        direction=payload.direction,
        content=payload.content,
        occurred_at=payload.occurred_at,
        actor_agent_id=payload.actor_agent_id,
        actor_name=payload.actor_name,
        details=dict(payload.details),
        status=CrmHistoryImportEventStatus.RECEIVED,
        created_at=now,
    )


def _canonical_event(staged: StagedCrmHistoryImportEvent, *, now: datetime) -> CrmConversationEvent:
    activity_id = _crm_activity_id(staged)
    direction = (
        CrmConversationEventDirection(staged.direction.value)
        if staged.direction is not None
        else None
    )
    return CrmConversationEvent(
        crm_conversation_event_id=uuid5(
            _PROMOTION_ID_NAMESPACE, f"{staged.workspace_id}:{activity_id}"
        ),
        workspace_id=staged.workspace_id,
        lead_id=staged.lead_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=activity_id,
        activity_type=staged.activity_type,
        direction=direction,
        occurred_at=staged.occurred_at,
        content=staged.content,
        actor_agent_id=staged.actor_agent_id,
        actor_name=staged.actor_name,
        details=dict(staged.details),
        source_payload_version="extension/v1",
        created_at=now,
        updated_at=now,
        canonical_identity=canonical_crm_event_identity(
            activity_type=staged.activity_type,
            occurred_at=staged.occurred_at,
            content=staged.content,
            direction=direction,
        ),
    )


def _crm_activity_id(staged: StagedCrmHistoryImportEvent) -> str:
    if staged.external_activity_id is None:
        return f"extension-fingerprint:{staged.fingerprint}"
    namespaced = f"extension:{staged.external_activity_id}"
    if len(namespaced) <= 255:
        return namespaced
    external_hash = hashlib.sha256(staged.external_activity_id.encode("utf-8")).hexdigest()
    return f"extension:{external_hash}"


def crm_history_export_batch_fingerprint(
    payloads: tuple[CrmHistoryImportEventPayload, ...],
) -> str:
    identities = sorted(
        {
            canonical_crm_event_identity(
                activity_type=payload.activity_type,
                occurred_at=payload.occurred_at,
                content=payload.content,
                direction=payload.direction.value if payload.direction is not None else None,
            )
            for payload in payloads
        }
    )
    encoded = json.dumps(identities, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _create_rejection(reason: CrmHistoryImportReasonCode) -> CreateCrmHistoryImportResult:
    return CreateCrmHistoryImportResult(
        status=CrmHistoryImportMutationStatus.REJECTED,
        reasons=(reason.value,),
    )


async def _append_audit(
    repository: AuthAuditLogRepository | None,
    *,
    event_type: AuthAuditEventType,
    job: CrmHistoryImportJob,
    now: datetime,
    actor_user_id: UUID | None,
    request_status: CrmHistoryImportMutationStatus | None = None,
) -> None:
    if repository is None:
        return
    await repository.append(
        AuthAuditLog(
            audit_log_id=uuid4(),
            workspace_id=job.workspace_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            event_details={
                "import_job_id": str(job.import_job_id),
                "lead_id": str(job.lead_id),
                "status": job.status.value,
                "received_count": str(job.received_count),
                "promoted_count": str(job.promoted_count),
                "duplicate_count": str(job.duplicate_count),
                "rejected_count": str(job.rejected_count),
                "failure_count": str(job.failure_count),
                "source": job.source.value,
                "source_device_id": str(job.source_device_id) if job.source_device_id else "",
                "request_status": (
                    request_status.value if request_status is not None else "created"
                ),
            },
            created_at=now,
        )
    )