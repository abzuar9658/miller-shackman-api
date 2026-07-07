from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.common.ids import UserId, WorkspaceId, WorkspaceMembershipId
from app.domain.identity import WorkspaceMembershipRole


@dataclass(frozen=True)
class AccessTokenSubject:
    user_id: UserId
    workspace_id: WorkspaceId | None
    membership_id: WorkspaceMembershipId | None
    role: WorkspaceMembershipRole | None


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    token_id: UUID
    subject: AccessTokenSubject
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DecodedAccessToken:
    token_id: UUID
    subject: AccessTokenSubject
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class OpaqueToken:
    plaintext: str
    token_hash: str


class InvalidAccessTokenError(ValueError):
    """Raised when an access token cannot be decoded or validated."""


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str:
        raise NotImplementedError

    def verify_password(self, password: str, password_hash: str) -> bool:
        raise NotImplementedError

    def needs_rehash(self, password_hash: str) -> bool:
        raise NotImplementedError


class AccessTokenService(Protocol):
    def issue_token(
        self,
        subject: AccessTokenSubject,
        *,
        issued_at: datetime,
        expires_at: datetime,
        token_id: UUID | None = None,
    ) -> IssuedAccessToken:
        raise NotImplementedError

    def decode_token(self, token: str) -> DecodedAccessToken:
        raise NotImplementedError


class OpaqueTokenService(Protocol):
    def generate_token(self) -> OpaqueToken:
        raise NotImplementedError

    def hash_token(self, token: str) -> str:
        raise NotImplementedError

    def verify_token(self, token: str, token_hash: str) -> bool:
        raise NotImplementedError
