from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import ExtensionDevice, ExtensionPairingCode
from app.infrastructure.persistence.postgres.extension_device_repository import (
    PostgresExtensionDeviceRepository,
    PostgresExtensionPairingCodeRepository,
)
from app.infrastructure.persistence.postgres.models import (
    ExtensionDeviceModel,
    ExtensionPairingCodeModel,
)

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
USER_ID = UUID("00000000-0000-0000-0000-000000000102")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000103")
CODE_ID = UUID("00000000-0000-0000-0000-000000000104")
DEVICE_ID = UUID("00000000-0000-0000-0000-000000000105")


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, *, value: object | None = None, values: list[object] | None = None) -> None:
        self._value = value
        self._values = values or []

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalar_one(self) -> object:
        assert self._value is not None
        return self._value

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _Session:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return self.result


def test_pairing_code_lookup_is_workspace_filtered_and_locked() -> None:
    session = _Session(_Result(value=_pairing_model()))
    result = _run(
        PostgresExtensionPairingCodeRepository(
            cast(AsyncSession, session)
        ).get_by_token_hash_for_update(WORKSPACE_ID, "hash::setup")
    )

    assert result == _pairing_code()
    statement = cast(Any, session.statements[0])
    assert "extension_pairing_codes.workspace_id" in str(statement)
    assert "extension_pairing_codes.token_hash" in str(statement)
    assert statement._for_update_arg is not None


def test_device_lookup_is_workspace_filtered_and_locked() -> None:
    session = _Session(_Result(value=_device_model()))
    result = _run(
        PostgresExtensionDeviceRepository(
            cast(AsyncSession, session)
        ).get_by_id_for_update(WORKSPACE_ID, DEVICE_ID)
    )

    assert result == _device()
    statement = cast(Any, session.statements[0])
    assert "extension_devices.workspace_id" in str(statement)
    assert "extension_devices.device_id" in str(statement)
    assert statement._for_update_arg is not None


def test_device_list_filters_workspace_and_user() -> None:
    session = _Session(_Result(values=[_device_model()]))
    result = _run(
        PostgresExtensionDeviceRepository(
            cast(AsyncSession, session)
        ).list_by_workspace_and_user(WORKSPACE_ID, USER_ID)
    )

    assert result == (_device(),)
    statement = str(session.statements[0])
    assert "extension_devices.workspace_id" in statement
    assert "extension_devices.user_id" in statement


def _pairing_code() -> ExtensionPairingCode:
    return ExtensionPairingCode(
        pairing_code_id=CODE_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        token_hash="hash::setup",
        expires_at=NOW + timedelta(minutes=15),
        claimed_at=None,
        revoked_at=None,
        created_by_user_id=ADMIN_ID,
        created_at=NOW,
    )


def _pairing_model() -> ExtensionPairingCodeModel:
    return ExtensionPairingCodeModel(**_pairing_code().__dict__)


def _device() -> ExtensionDevice:
    return ExtensionDevice(
        device_id=DEVICE_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        device_name="Chrome on macOS",
        extension_version="0.2.0",
        credential_hash="hash::device",
        created_at=NOW,
        last_seen_at=None,
        revoked_at=None,
        revoked_by_user_id=None,
        revocation_reason=None,
    )


def _device_model() -> ExtensionDeviceModel:
    return ExtensionDeviceModel(**_device().__dict__)


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)