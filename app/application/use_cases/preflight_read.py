from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.application.ports.preflight_digest import (
    PreflightDigestIssueStatus,
    PreflightDigestRecord,
    PreflightDigestRepository,
)
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
    limit: int = 50,
    now: datetime | None = None,
) -> PreflightListResult:
    if not _can_view_workspace_preflight(actor):
        return PreflightListResult(
            status=PreflightReadStatus.REJECTED,
            reasons=(PreflightReadReasonCode.PERMISSION_DENIED,),
        )

    effective_now = now or datetime.now(UTC)
    digests = await repository.list_digests_for_workspace(workspace_id, limit=limit)
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
    now: datetime | None = None,
) -> PreflightDetailResult:
    if not _can_view_workspace_preflight(actor):
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
    effective_now = now or datetime.now(UTC)
    return PreflightDetailResult(
        status=PreflightReadStatus.OK,
        view=_summary_view(digest, now=effective_now),
    )


def _summary_view(
    digest: PreflightDigestRecord, *, now: datetime
) -> PreflightDigestSummaryView:
    return PreflightDigestSummaryView(
        digest=digest,
        status=_view_status(digest, now=now),
        lead_count=len(digest.entries),
        veto_count=len(digest.vetoes),
        recipient_count=len({entry.recipient_id for entry in digest.entries}),
    )


def _view_status(
    digest: PreflightDigestRecord, *, now: datetime
) -> PreflightDigestViewStatus:
    if digest.status == PreflightDigestIssueStatus.FAILED:
        return PreflightDigestViewStatus.FAILED
    if digest.status == PreflightDigestIssueStatus.UNCERTAIN:
        return PreflightDigestViewStatus.UNCERTAIN
    if digest.veto_window_expires_at is None or now >= digest.veto_window_expires_at:
        return PreflightDigestViewStatus.READY
    return PreflightDigestViewStatus.PENDING


def _can_view_workspace_preflight(actor: AuthenticatedActor) -> bool:
    return bool(evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed)
