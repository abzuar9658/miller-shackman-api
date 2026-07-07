from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.services.refresh_sessions import (
    RefreshSessionUseReason,
    evaluate_refresh_session_for_use,
    revoke_refresh_session_family,
    rotate_refresh_session,
)
from app.domain.identity import RefreshSession, RefreshSessionRevocationReason

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
USER_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000003")
NEXT_SESSION_ID = UUID("00000000-0000-0000-0000-000000000004")
FAMILY_ID = UUID("00000000-0000-0000-0000-000000000005")


def test_evaluate_refresh_session_accepts_active_session() -> None:
    decision = evaluate_refresh_session_for_use(_session(), now=NOW)

    assert decision.accepted is True
    assert decision.reason == RefreshSessionUseReason.ACTIVE


def test_evaluate_refresh_session_rejects_expired_session() -> None:
    decision = evaluate_refresh_session_for_use(
        _session(expires_at=NOW - timedelta(seconds=1)),
        now=NOW,
    )

    assert decision.accepted is False
    assert decision.reason == RefreshSessionUseReason.EXPIRED


def test_evaluate_refresh_session_treats_rotated_session_as_reuse() -> None:
    decision = evaluate_refresh_session_for_use(
        _session(
            revoked_at=NOW - timedelta(minutes=1),
            revoked_reason=RefreshSessionRevocationReason.ROTATED,
        ),
        now=NOW,
    )

    assert decision.accepted is False
    assert decision.reason == RefreshSessionUseReason.REUSE_DETECTED


def test_rotate_refresh_session_revokes_current_and_creates_replacement() -> None:
    result = rotate_refresh_session(
        _session(),
        replacement_session_id=NEXT_SESSION_ID,
        replacement_token_hash="new-token-hash",
        replacement_expires_at=NOW + timedelta(days=30),
        now=NOW,
    )

    assert result.revoked_session.revoked_at == NOW
    assert result.revoked_session.revoked_reason == RefreshSessionRevocationReason.ROTATED
    assert result.revoked_session.last_used_at == NOW
    assert result.replacement_session.session_id == NEXT_SESSION_ID
    assert result.replacement_session.rotated_from_session_id == SESSION_ID
    assert result.replacement_session.family_id == FAMILY_ID
    assert result.replacement_session.refresh_token_hash == "new-token-hash"
    assert result.replacement_session.revoked_at is None


def test_revoke_refresh_session_family_only_updates_active_sessions() -> None:
    active = _session()
    already_revoked = _session(
        session_id=NEXT_SESSION_ID,
        revoked_at=NOW - timedelta(minutes=5),
        revoked_reason=RefreshSessionRevocationReason.LOGOUT,
    )

    revoked_sessions = revoke_refresh_session_family(
        (active, already_revoked),
        reason=RefreshSessionRevocationReason.REUSE_DETECTED,
        now=NOW,
    )

    assert revoked_sessions[0].revoked_at == NOW
    assert revoked_sessions[0].revoked_reason == RefreshSessionRevocationReason.REUSE_DETECTED
    assert revoked_sessions[1] == already_revoked


def _session(
    *,
    session_id: UUID = SESSION_ID,
    expires_at: datetime = NOW + timedelta(days=30),
    revoked_at: datetime | None = None,
    revoked_reason: RefreshSessionRevocationReason | None = None,
) -> RefreshSession:
    return RefreshSession(
        session_id=session_id,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        refresh_token_hash="token-hash",
        family_id=FAMILY_ID,
        rotated_from_session_id=None,
        expires_at=expires_at,
        revoked_at=revoked_at,
        revoked_reason=revoked_reason,
        created_at=NOW - timedelta(days=1),
        last_used_at=None,
    )