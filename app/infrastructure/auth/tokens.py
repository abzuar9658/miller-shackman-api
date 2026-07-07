import hashlib
import secrets
from datetime import UTC, datetime
from hmac import compare_digest
from typing import cast
from uuid import UUID, uuid4

from jose import JWTError, jwt  # type: ignore[import-untyped]

from app.application.ports.auth import (
    AccessTokenSubject,
    DecodedAccessToken,
    InvalidAccessTokenError,
    IssuedAccessToken,
    OpaqueToken,
)
from app.domain.identity import WorkspaceMembershipRole


class JoseAccessTokenService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        issuer: str = "miller-schackman-api",
        audience: str = "miller-schackman-api",
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience

    def issue_token(
        self,
        subject: AccessTokenSubject,
        *,
        issued_at: datetime,
        expires_at: datetime,
        token_id: UUID | None = None,
    ) -> IssuedAccessToken:
        resolved_token_id = token_id or uuid4()
        payload = {
            "sub": str(subject.user_id),
            "jti": str(resolved_token_id),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        if subject.workspace_id is not None:
            payload["workspace_id"] = str(subject.workspace_id)
        if subject.membership_id is not None:
            payload["membership_id"] = str(subject.membership_id)
        if subject.role is not None:
            payload["role"] = subject.role.value

        token = cast(str, jwt.encode(payload, self._secret, algorithm=self._algorithm))
        return IssuedAccessToken(
            token=token,
            token_id=resolved_token_id,
            subject=subject,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def decode_token(self, token: str) -> DecodedAccessToken:
        try:
            payload = cast(
                dict[str, object],
                jwt.decode(
                    token,
                    self._secret,
                    algorithms=[self._algorithm],
                    audience=self._audience,
                    issuer=self._issuer,
                    options={
                        "require_sub": True,
                        "require_jti": True,
                        "require_iat": True,
                        "require_exp": True,
                    },
                ),
            )
            role_value = _optional_str(payload, "role")
            role = WorkspaceMembershipRole(role_value) if role_value is not None else None
            return DecodedAccessToken(
                token_id=UUID(_required_str(payload, "jti")),
                subject=AccessTokenSubject(
                    user_id=UUID(_required_str(payload, "sub")),
                    workspace_id=_uuid_or_none(payload.get("workspace_id")),
                    membership_id=_uuid_or_none(payload.get("membership_id")),
                    role=role,
                ),
                issued_at=datetime.fromtimestamp(_required_int(payload, "iat"), tz=UTC),
                expires_at=datetime.fromtimestamp(_required_int(payload, "exp"), tz=UTC),
            )
        except (JWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidAccessTokenError("Invalid access token") from exc


class SecureOpaqueTokenService:
    def __init__(self, *, token_bytes: int = 32) -> None:
        self._token_bytes = token_bytes

    def generate_token(self) -> OpaqueToken:
        plaintext = secrets.token_urlsafe(self._token_bytes)
        return OpaqueToken(plaintext=plaintext, token_hash=self.hash_token(plaintext))

    def hash_token(self, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return digest

    def verify_token(self, token: str, token_hash: str) -> bool:
        return compare_digest(self.hash_token(token), token_hash)


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    return str(value)


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    return int(str(value))
