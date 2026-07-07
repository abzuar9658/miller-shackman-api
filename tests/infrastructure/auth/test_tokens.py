from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.application.ports.auth import AccessTokenSubject, InvalidAccessTokenError
from app.domain.identity import WorkspaceMembershipRole
from app.infrastructure.auth.tokens import JoseAccessTokenService, SecureOpaqueTokenService

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
USER_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000003")
TOKEN_ID = UUID("00000000-0000-0000-0000-000000000004")


def test_issue_and_decode_access_token_round_trip() -> None:
    service = JoseAccessTokenService(secret="test-secret")
    subject = AccessTokenSubject(
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        membership_id=MEMBERSHIP_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )

    issued = service.issue_token(
        subject,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        token_id=TOKEN_ID,
    )
    decoded = service.decode_token(issued.token)

    assert decoded.token_id == TOKEN_ID
    assert decoded.subject == subject
    assert decoded.issued_at == NOW
    assert decoded.expires_at == NOW + timedelta(minutes=15)


def test_decode_access_token_rejects_wrong_secret() -> None:
    issuer = JoseAccessTokenService(secret="first-secret")
    decoder = JoseAccessTokenService(secret="second-secret")

    issued = issuer.issue_token(
        AccessTokenSubject(
            user_id=USER_ID,
            workspace_id=None,
            membership_id=None,
            role=None,
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        token_id=TOKEN_ID,
    )

    with pytest.raises(InvalidAccessTokenError):
        decoder.decode_token(issued.token)


def test_generate_opaque_token_hashes_and_verifies() -> None:
    service = SecureOpaqueTokenService()

    token = service.generate_token()

    assert token.plaintext
    assert token.token_hash
    assert token.plaintext != token.token_hash
    assert service.verify_token(token.plaintext, token.token_hash) is True
    assert service.verify_token("different-token", token.token_hash) is False
