from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common.ids import RefreshSessionId
from app.domain.identity import RefreshSession, RefreshSessionRevocationReason


class RefreshSessionUseReason(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REUSE_DETECTED = "reuse_detected"


@dataclass(frozen=True)
class RefreshSessionUseDecision:
    accepted: bool
    reason: RefreshSessionUseReason


@dataclass(frozen=True)
class RefreshSessionRotationResult:
    revoked_session: RefreshSession
    replacement_session: RefreshSession


def evaluate_refresh_session_for_use(
    session: RefreshSession,
    *,
    now: datetime,
) -> RefreshSessionUseDecision:
    if session.expires_at <= now:
        return RefreshSessionUseDecision(
            accepted=False,
            reason=RefreshSessionUseReason.EXPIRED,
        )
    if session.revoked_at is None:
        return RefreshSessionUseDecision(
            accepted=True,
            reason=RefreshSessionUseReason.ACTIVE,
        )
    if session.revoked_reason == RefreshSessionRevocationReason.ROTATED:
        return RefreshSessionUseDecision(
            accepted=False,
            reason=RefreshSessionUseReason.REUSE_DETECTED,
        )
    return RefreshSessionUseDecision(
        accepted=False,
        reason=RefreshSessionUseReason.REVOKED,
    )


def rotate_refresh_session(
    session: RefreshSession,
    *,
    replacement_session_id: RefreshSessionId,
    replacement_token_hash: str,
    replacement_expires_at: datetime,
    now: datetime,
) -> RefreshSessionRotationResult:
    revoked_session = replace(
        session,
        revoked_at=now,
        revoked_reason=RefreshSessionRevocationReason.ROTATED,
        last_used_at=now,
    )
    replacement_session = RefreshSession(
        session_id=replacement_session_id,
        user_id=session.user_id,
        workspace_id=session.workspace_id,
        refresh_token_hash=replacement_token_hash,
        family_id=session.family_id,
        rotated_from_session_id=session.session_id,
        expires_at=replacement_expires_at,
        revoked_at=None,
        revoked_reason=None,
        created_at=now,
        last_used_at=None,
    )
    return RefreshSessionRotationResult(
        revoked_session=revoked_session,
        replacement_session=replacement_session,
    )


def revoke_refresh_session_family(
    sessions: tuple[RefreshSession, ...],
    *,
    reason: RefreshSessionRevocationReason,
    now: datetime,
) -> tuple[RefreshSession, ...]:
    return tuple(_revoke_refresh_session(session, reason=reason, now=now) for session in sessions)


def _revoke_refresh_session(
    session: RefreshSession,
    *,
    reason: RefreshSessionRevocationReason,
    now: datetime,
) -> RefreshSession:
    if session.revoked_at is not None:
        return session
    return replace(
        session,
        revoked_at=now,
        revoked_reason=reason,
    )
