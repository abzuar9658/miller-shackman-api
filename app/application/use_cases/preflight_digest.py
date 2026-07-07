from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from app.application.ports.notifications import (
    NotificationProvider,
    PreflightDigestNotification,
    PreflightDigestNotificationLead,
)
from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.domain.campaigns.start_queue import (
    CampaignStartCandidate,
    CampaignStartContext,
    CampaignStartPolicy,
    CampaignStatus,
    StartQueueReasonCode,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId


class PreflightDigestReasonCode(StrEnum):
    MISSING_REQUIRED_DATA = "missing_required_data"
    CAMPAIGN_NOT_ACTIVE = "campaign_not_active"
    DIGEST_NOT_REQUIRED = "digest_not_required"
    MISSING_DIGEST_RECIPIENT = "missing_digest_recipient"
    DIGEST_ALREADY_ISSUED = "digest_already_issued"
    DIGEST_STATE_UNCERTAIN = "digest_state_uncertain"
    NOTIFICATION_FAILED = "notification_failed"
    CANDIDATE_NOT_IN_DIGEST = "candidate_not_in_digest"
    UNAUTHORIZED_VETO_ACTOR = "unauthorized_veto_actor"
    VETO_WINDOW_EXPIRED = "veto_window_expired"
    DUPLICATE_VETO = "duplicate_veto"


class PreflightDigestPreparationStatus(StrEnum):
    ISSUED = "issued"
    ALREADY_ISSUED = "already_issued"
    NOT_REQUIRED = "not_required"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class PreflightVetoStatus(StrEnum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class VetoActorRole(StrEnum):
    ASSIGNED_AGENT = "assigned_agent"
    MANAGER = "manager"
    BROKERAGE_ADMIN = "brokerage_admin"
    UNAUTHORIZED = "unauthorized"


@dataclass(frozen=True)
class PreflightDigestCandidate:
    start_candidate: CampaignStartCandidate
    recipient_id: str | None
    recipient_destination: str | None
    lead_display_name: str


@dataclass(frozen=True)
class PreflightDigestHeldBackLead:
    lead_id: LeadId
    reasons: tuple[PreflightDigestReasonCode, ...]


@dataclass(frozen=True)
class PreflightDigestPreparationResult:
    status: PreflightDigestPreparationStatus
    digest_id: str | None = None
    digest_sent_at: datetime | None = None
    veto_window_expires_at: datetime | None = None
    recipients_notified: tuple[str, ...] = ()
    included_lead_ids: tuple[LeadId, ...] = ()
    held_back: tuple[PreflightDigestHeldBackLead, ...] = ()
    idempotency_keys: tuple[str, ...] = ()
    reasons: tuple[PreflightDigestReasonCode, ...] = ()


@dataclass(frozen=True)
class PreflightVetoResult:
    status: PreflightVetoStatus
    digest_id: str | None
    lead_id: LeadId
    actor_id: str
    recorded: bool
    recorded_at: datetime | None = None
    duplicate: bool = False
    reasons: tuple[PreflightDigestReasonCode, ...] = ()


@dataclass(frozen=True)
class PreflightVetoPolicy:
    authorized_manager_roles: frozenset[VetoActorRole] = frozenset(
        {VetoActorRole.MANAGER, VetoActorRole.BROKERAGE_ADMIN},
    )


async def prepare_preflight_digest(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    candidates: Iterable[PreflightDigestCandidate],
    start_policy: CampaignStartPolicy,
    start_context: CampaignStartContext,
    repository: PreflightDigestRepository,
    notification_provider: NotificationProvider,
    now: datetime,
    digest_id_factory: Callable[[], str] | None = None,
) -> PreflightDigestPreparationResult:
    existing = await repository.get_digest(workspace_id, campaign_id, batch_id)
    if existing is not None:
        existing_result = _existing_digest_result(existing)
        if existing_result is not None:
            return existing_result

    digest_id = (digest_id_factory or _default_digest_id)()
    entries, held_back = _build_digest_entries(
        candidates=tuple(candidates),
        start_policy=start_policy,
        start_context=start_context,
        now=now,
    )
    if not entries:
        result_reasons = _result_reasons_from_held_back(held_back)
        result_status = PreflightDigestPreparationStatus.NOT_REQUIRED
        if result_reasons != (PreflightDigestReasonCode.DIGEST_NOT_REQUIRED,):
            result_status = PreflightDigestPreparationStatus.FAILED
        return PreflightDigestPreparationResult(
            status=result_status,
            held_back=tuple(held_back),
            reasons=result_reasons,
        )

    veto_window_expires_at = now + timedelta(hours=start_policy.veto_window_hours)
    notification_records: list[PreflightDigestNotificationRecord] = []
    for recipient_id, recipient_entries in _group_entries_by_recipient(entries):
        idempotency_key = _digest_idempotency_key(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            recipient_id=recipient_id,
        )
        notification = _notification_from_entries(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            digest_id=digest_id,
            batch_id=batch_id,
            recipient_id=recipient_id,
            entries=recipient_entries,
            veto_window_expires_at=veto_window_expires_at,
            idempotency_key=idempotency_key,
        )
        send_result = await notification_provider.send_preflight_digest(notification)
        notification_records.append(
            PreflightDigestNotificationRecord(
                recipient_id=recipient_id,
                idempotency_key=idempotency_key,
                accepted=send_result.accepted,
                provider_reference=send_result.provider_reference,
                uncertain=send_result.uncertain,
            ),
        )
        if send_result.uncertain or not send_result.accepted:
            status = PreflightDigestIssueStatus.UNCERTAIN
            result_status = PreflightDigestPreparationStatus.UNCERTAIN
            reason = PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN
            if not notification_records[:-1] and not send_result.uncertain:
                status = PreflightDigestIssueStatus.FAILED
                result_status = PreflightDigestPreparationStatus.FAILED
                reason = PreflightDigestReasonCode.NOTIFICATION_FAILED
            await repository.save_digest(
                PreflightDigestRecord(
                    digest_id=digest_id,
                    workspace_id=workspace_id,
                    campaign_id=campaign_id,
                    batch_id=batch_id,
                    status=status,
                    entries=entries,
                    notification_records=tuple(notification_records),
                ),
            )
            return PreflightDigestPreparationResult(
                status=result_status,
                digest_id=digest_id,
                included_lead_ids=tuple(entry.lead_id for entry in entries),
                held_back=tuple(held_back),
                idempotency_keys=tuple(record.idempotency_key for record in notification_records),
                reasons=(reason,),
            )

    digest = PreflightDigestRecord(
        digest_id=digest_id,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        status=PreflightDigestIssueStatus.ISSUED,
        entries=entries,
        notification_records=tuple(notification_records),
        digest_sent_at=now,
        veto_window_expires_at=veto_window_expires_at,
    )
    await repository.save_digest(digest)
    return PreflightDigestPreparationResult(
        status=PreflightDigestPreparationStatus.ISSUED,
        digest_id=digest.digest_id,
        digest_sent_at=digest.digest_sent_at,
        veto_window_expires_at=digest.veto_window_expires_at,
        recipients_notified=tuple(record.recipient_id for record in notification_records),
        included_lead_ids=tuple(entry.lead_id for entry in entries),
        held_back=tuple(held_back),
        idempotency_keys=tuple(record.idempotency_key for record in notification_records),
    )


async def record_preflight_veto(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    lead_id: LeadId,
    actor_id: str,
    actor_role: VetoActorRole,
    repository: PreflightDigestRepository,
    policy: PreflightVetoPolicy,
    now: datetime,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> PreflightVetoResult:
    digest = await repository.get_digest(workspace_id, campaign_id, batch_id)
    if digest is None:
        return _rejected_veto_result(
            digest_id=None,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=PreflightDigestReasonCode.MISSING_REQUIRED_DATA,
        )
    if digest.status != PreflightDigestIssueStatus.ISSUED or digest.veto_window_expires_at is None:
        return _rejected_veto_result(
            digest_id=digest.digest_id,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN,
        )

    matching_entry = _entry_for_lead(digest, lead_id)
    if matching_entry is None:
        return _rejected_veto_result(
            digest_id=digest.digest_id,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=PreflightDigestReasonCode.CANDIDATE_NOT_IN_DIGEST,
        )
    if not _actor_can_veto(matching_entry, actor_id, actor_role, policy):
        return _rejected_veto_result(
            digest_id=digest.digest_id,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=PreflightDigestReasonCode.UNAUTHORIZED_VETO_ACTOR,
        )
    if now >= digest.veto_window_expires_at:
        return _rejected_veto_result(
            digest_id=digest.digest_id,
            lead_id=lead_id,
            actor_id=actor_id,
            reason=PreflightDigestReasonCode.VETO_WINDOW_EXPIRED,
        )
    if lead_id in digest.vetoed_lead_ids:
        return PreflightVetoResult(
            status=PreflightVetoStatus.DUPLICATE,
            digest_id=digest.digest_id,
            lead_id=lead_id,
            actor_id=actor_id,
            recorded=False,
            duplicate=True,
            reasons=(PreflightDigestReasonCode.DUPLICATE_VETO,),
        )

    veto = PreflightVetoRecord(
        lead_id=lead_id,
        actor_id=actor_id,
        recorded_at=now,
        idempotency_key=idempotency_key
        or _veto_idempotency_key(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            lead_id=lead_id,
            actor_id=actor_id,
        ),
        reason=reason,
    )
    await repository.save_digest(replace(digest, vetoes=(*digest.vetoes, veto)))
    return PreflightVetoResult(
        status=PreflightVetoStatus.RECORDED,
        digest_id=digest.digest_id,
        lead_id=lead_id,
        actor_id=actor_id,
        recorded=True,
        recorded_at=now,
    )


def campaign_start_context_from_digest(
    *,
    campaign_status: CampaignStatus,
    digest: PreflightDigestRecord | None,
    started_today_count: int = 0,
    is_first_batch: bool = True,
) -> CampaignStartContext:
    if digest is None or digest.status != PreflightDigestIssueStatus.ISSUED:
        return CampaignStartContext(
            campaign_status=campaign_status,
            started_today_count=started_today_count,
            is_first_batch=is_first_batch,
        )
    return CampaignStartContext(
        campaign_status=campaign_status,
        started_today_count=started_today_count,
        is_first_batch=is_first_batch,
        digest_sent_at=digest.digest_sent_at,
        vetoed_lead_ids=digest.vetoed_lead_ids,
    )


def _default_digest_id() -> str:
    return str(uuid4())


def _existing_digest_result(
    digest: PreflightDigestRecord,
) -> PreflightDigestPreparationResult | None:
    if digest.status == PreflightDigestIssueStatus.ISSUED:
        return PreflightDigestPreparationResult(
            status=PreflightDigestPreparationStatus.ALREADY_ISSUED,
            digest_id=digest.digest_id,
            digest_sent_at=digest.digest_sent_at,
            veto_window_expires_at=digest.veto_window_expires_at,
            recipients_notified=tuple(
                record.recipient_id for record in digest.notification_records
            ),
            included_lead_ids=tuple(entry.lead_id for entry in digest.entries),
            idempotency_keys=tuple(
                record.idempotency_key for record in digest.notification_records
            ),
            reasons=(PreflightDigestReasonCode.DIGEST_ALREADY_ISSUED,),
        )
    if digest.status == PreflightDigestIssueStatus.UNCERTAIN:
        return PreflightDigestPreparationResult(
            status=PreflightDigestPreparationStatus.UNCERTAIN,
            digest_id=digest.digest_id,
            included_lead_ids=tuple(entry.lead_id for entry in digest.entries),
            idempotency_keys=tuple(
                record.idempotency_key for record in digest.notification_records
            ),
            reasons=(PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN,),
        )
    return None


def _build_digest_entries(
    *,
    candidates: tuple[PreflightDigestCandidate, ...],
    start_policy: CampaignStartPolicy,
    start_context: CampaignStartContext,
    now: datetime,
) -> tuple[tuple[PreflightDigestEntry, ...], list[PreflightDigestHeldBackLead]]:
    entries: list[PreflightDigestEntry] = []
    held_back: list[PreflightDigestHeldBackLead] = []
    for candidate in candidates:
        reason = _digest_candidate_blocking_reason(candidate, start_policy, start_context, now)
        if reason is not None:
            held_back.append(
                PreflightDigestHeldBackLead(
                    lead_id=candidate.start_candidate.lead_id,
                    reasons=(reason,),
                ),
            )
            continue
        assert candidate.recipient_id is not None
        assert candidate.recipient_destination is not None
        entries.append(
            PreflightDigestEntry(
                lead_id=candidate.start_candidate.lead_id,
                recipient_id=candidate.recipient_id,
                recipient_destination=candidate.recipient_destination,
                display_name=candidate.lead_display_name,
            ),
        )
    return tuple(entries), held_back


def _digest_candidate_blocking_reason(
    candidate: PreflightDigestCandidate,
    start_policy: CampaignStartPolicy,
    start_context: CampaignStartContext,
    now: datetime,
) -> PreflightDigestReasonCode | None:
    start_decision = evaluate_campaign_start_batch(
        [candidate.start_candidate],
        start_policy,
        start_context,
        now,
    )
    held_back_reasons = start_decision.held_back[0].reasons if start_decision.held_back else ()
    if StartQueueReasonCode.CAMPAIGN_INACTIVE in held_back_reasons:
        return PreflightDigestReasonCode.CAMPAIGN_NOT_ACTIVE
    if StartQueueReasonCode.PREFLIGHT_DIGEST_PENDING not in held_back_reasons:
        return PreflightDigestReasonCode.DIGEST_NOT_REQUIRED
    if not candidate.recipient_id or not candidate.recipient_destination:
        return PreflightDigestReasonCode.MISSING_DIGEST_RECIPIENT
    return None


def _group_entries_by_recipient(
    entries: tuple[PreflightDigestEntry, ...],
) -> tuple[tuple[str, tuple[PreflightDigestEntry, ...]], ...]:
    grouped: dict[str, list[PreflightDigestEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.recipient_id, []).append(entry)
    return tuple((recipient_id, tuple(group)) for recipient_id, group in grouped.items())


def _result_reasons_from_held_back(
    held_back: list[PreflightDigestHeldBackLead],
) -> tuple[PreflightDigestReasonCode, ...]:
    reasons: list[PreflightDigestReasonCode] = []
    for item in held_back:
        for reason in item.reasons:
            if reason not in reasons:
                reasons.append(reason)
    return tuple(reasons) or (PreflightDigestReasonCode.DIGEST_NOT_REQUIRED,)


def _notification_from_entries(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    digest_id: str,
    batch_id: str,
    recipient_id: str,
    entries: tuple[PreflightDigestEntry, ...],
    veto_window_expires_at: datetime,
    idempotency_key: str,
) -> PreflightDigestNotification:
    first_entry = entries[0]
    return PreflightDigestNotification(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        digest_id=digest_id,
        batch_id=batch_id,
        recipient_id=recipient_id,
        recipient_destination=first_entry.recipient_destination,
        leads=tuple(
            PreflightDigestNotificationLead(
                lead_id=entry.lead_id,
                display_name=entry.display_name,
            )
            for entry in entries
        ),
        veto_window_expires_at=veto_window_expires_at,
        idempotency_key=idempotency_key,
    )


def _entry_for_lead(
    digest: PreflightDigestRecord,
    lead_id: LeadId,
) -> PreflightDigestEntry | None:
    for entry in digest.entries:
        if entry.lead_id == lead_id:
            return entry
    return None


def _actor_can_veto(
    entry: PreflightDigestEntry,
    actor_id: str,
    actor_role: VetoActorRole,
    policy: PreflightVetoPolicy,
) -> bool:
    if actor_role == VetoActorRole.ASSIGNED_AGENT:
        return actor_id == entry.recipient_id
    return actor_role in policy.authorized_manager_roles


def _rejected_veto_result(
    *,
    digest_id: str | None,
    lead_id: LeadId,
    actor_id: str,
    reason: PreflightDigestReasonCode,
) -> PreflightVetoResult:
    return PreflightVetoResult(
        status=PreflightVetoStatus.REJECTED,
        digest_id=digest_id,
        lead_id=lead_id,
        actor_id=actor_id,
        recorded=False,
        reasons=(reason,),
    )


def _digest_idempotency_key(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    recipient_id: str,
) -> str:
    return f"preflight-digest:{workspace_id}:{campaign_id}:{batch_id}:{recipient_id}:v1"


def _veto_idempotency_key(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    lead_id: LeadId,
    actor_id: str,
) -> str:
    return f"preflight-veto:{workspace_id}:{campaign_id}:{batch_id}:{lead_id}:{actor_id}:v1"
