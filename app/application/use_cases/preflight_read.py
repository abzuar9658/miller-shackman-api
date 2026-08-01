from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.application.ports.preflight_digest import (
    PreflightDigestIssueStatus,
    PreflightDigestRecord,
    PreflightDigestRepository,
)
from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.application.services.preflight_actor_resolution import actor_preflight_recipient_ids
from app.domain.common.ids import WorkspaceId
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission


class PreflightReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class PreflightReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    DIGEST_NOT_FOUND = "digest_not_found"


class PreflightDigestViewStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class PreflightDigestSummaryView:
    digest: PreflightDigestRecord
    status: PreflightDigestViewStatus
    lead_count: int
    veto_count: int
    recipient_count: int


@dataclass(frozen=True)
class PreflightListResult:
    status: PreflightReadStatus
    views: tuple[PreflightDigestSummaryView, ...] = ()
    reasons: tuple[PreflightReadReasonCode, ...] = ()


@dataclass(frozen=True)
class PreflightDetailResult:
    status: PreflightReadStatus
    view: PreflightDigestSummaryView | None = None
    reasons: tuple[PreflightReadReasonCode, ...] = ()


async def list_preflight_digest_views(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    repository: PreflightDigestRepository,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
    limit: int = 50,
    now: datetime | None = None,
) -> PreflightListResult:
    read_mode = _preflight_read_mode(actor)
    if read_mode == _PreflightReadMode.NONE:
        return PreflightListResult(
            status=PreflightReadStatus.REJECTED,
            reasons=(PreflightReadReasonCode.PERMISSION_DENIED,),
        )

    effective_now = now or datetime.now(UTC)
    digests = await repository.list_digests_for_workspace(workspace_id, limit=limit)
    if read_mode == _PreflightReadMode.OWN_ONLY:
        recipient_ids = await actor_preflight_recipient_ids(
            actor=actor,
            workspace_id=workspace_id,
            crm_agent_repository=crm_agent_repository,
            workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        )
        digests = _digests_visible_to_actor(digests, recipient_ids)

    return PreflightListResult(
        status=PreflightReadStatus.OK,
        views=tuple(_summary_view(digest, now=effective_now) for digest in digests),
    )


async def get_preflight_digest_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    digest_id: str,
    repository: PreflightDigestRepository,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
    now: datetime | None = None,
) -> PreflightDetailResult:
    read_mode = _preflight_read_mode(actor)
    if read_mode == _PreflightReadMode.NONE:
        return PreflightDetailResult(
            status=PreflightReadStatus.REJECTED,
            reasons=(PreflightReadReasonCode.PERMISSION_DENIED,),
        )

    digest = await repository.get_digest_by_id(workspace_id, digest_id)
    if digest is None:
        return PreflightDetailResult(
            status=PreflightReadStatus.NOT_FOUND,
            reasons=(PreflightReadReasonCode.DIGEST_NOT_FOUND,),
        )

    if read_mode == _PreflightReadMode.OWN_ONLY:
        recipient_ids = await actor_preflight_recipient_ids(
            actor=actor,
            workspace_id=workspace_id,
            crm_agent_repository=crm_agent_repository,
            workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        )
        if not _digest_has_visible_entry(digest, recipient_ids):
            return PreflightDetailResult(
                status=PreflightReadStatus.NOT_FOUND,
                reasons=(PreflightReadReasonCode.DIGEST_NOT_FOUND,),
            )
        digest = _filtered_digest_for_actor(digest, recipient_ids)

    effective_now = now or datetime.now(UTC)
    return PreflightDetailResult(
        status=PreflightReadStatus.OK,
        view=_summary_view(digest, now=effective_now),
    )


class _PreflightReadMode(StrEnum):
    NONE = "none"
    WORKSPACE = "workspace"
    OWN_ONLY = "own_only"


def _preflight_read_mode(actor: AuthenticatedActor) -> _PreflightReadMode:
    if evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed:
        return _PreflightReadMode.WORKSPACE
    if evaluate_permission(actor, PermissionCapability.VIEW_OWN_PREFLIGHT_LEAD).allowed:
        return _PreflightReadMode.OWN_ONLY
    return _PreflightReadMode.NONE


def _digests_visible_to_actor(
    digests: tuple[PreflightDigestRecord, ...],
    recipient_ids: frozenset[str],
) -> tuple[PreflightDigestRecord, ...]:
    return tuple(digest for digest in digests if _digest_has_visible_entry(digest, recipient_ids))


def _digest_has_visible_entry(
    digest: PreflightDigestRecord,
    recipient_ids: frozenset[str],
) -> bool:
    return any(entry.recipient_id in recipient_ids for entry in digest.entries)


def _filtered_digest_for_actor(
    digest: PreflightDigestRecord,
    recipient_ids: frozenset[str],
) -> PreflightDigestRecord:
    visible_entries = tuple(
        entry for entry in digest.entries if entry.recipient_id in recipient_ids
    )
    return PreflightDigestRecord(
        digest_id=digest.digest_id,
        workspace_id=digest.workspace_id,
        campaign_id=digest.campaign_id,
        batch_id=digest.batch_id,
        status=digest.status,
        entries=visible_entries,
        notification_records=tuple(
            record for record in digest.notification_records if record.recipient_id in recipient_ids
        ),
        digest_sent_at=digest.digest_sent_at,
        veto_window_expires_at=digest.veto_window_expires_at,
        vetoes=digest.vetoes,
    )


def _summary_view(digest: PreflightDigestRecord, *, now: datetime) -> PreflightDigestSummaryView:
    return PreflightDigestSummaryView(
        digest=digest,
        status=_view_status(digest, now=now),
        lead_count=len(digest.entries),
        veto_count=len(digest.vetoes),
        recipient_count=len({entry.recipient_id for entry in digest.entries}),
    )


def _view_status(digest: PreflightDigestRecord, *, now: datetime) -> PreflightDigestViewStatus:
    if digest.status == PreflightDigestIssueStatus.FAILED:
        return PreflightDigestViewStatus.FAILED
    if digest.status == PreflightDigestIssueStatus.UNCERTAIN:
        return PreflightDigestViewStatus.UNCERTAIN
    if digest.veto_window_expires_at is None or now >= digest.veto_window_expires_at:
        return PreflightDigestViewStatus.READY
    return PreflightDigestViewStatus.PENDING
