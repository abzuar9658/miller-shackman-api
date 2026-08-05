from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import ExtensionDeviceId, UserId, WorkspaceId
from app.domain.identity import ExtensionDevice, ExtensionPairingCode
from app.infrastructure.persistence.postgres.models import (
    ExtensionDeviceModel,
    ExtensionPairingCodeModel,
)


class PostgresExtensionPairingCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash_for_update(
        self,
        workspace_id: WorkspaceId,
        token_hash: str,
    ) -> ExtensionPairingCode | None:
        result = await self._session.execute(
            select(ExtensionPairingCodeModel)
            .where(
                ExtensionPairingCodeModel.workspace_id == workspace_id,
                ExtensionPairingCodeModel.token_hash == token_hash,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _pairing_code_from_model(model) if model else None

    async def revoke_pending_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        *,
        revoked_at: datetime,
    ) -> int:
        result = await self._session.execute(
            update(ExtensionPairingCodeModel)
            .where(
                ExtensionPairingCodeModel.workspace_id == workspace_id,
                ExtensionPairingCodeModel.user_id == user_id,
                ExtensionPairingCodeModel.claimed_at.is_(None),
                ExtensionPairingCodeModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .returning(ExtensionPairingCodeModel.pairing_code_id)
        )
        return len(result.scalars().all())

    async def save(self, pairing_code: ExtensionPairingCode) -> ExtensionPairingCode:
        values = _pairing_code_to_values(pairing_code)
        updates = dict(values)
        updates.pop("pairing_code_id")
        result = await self._session.execute(
            insert(ExtensionPairingCodeModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["pairing_code_id"],
                set_=updates,
            )
            .returning(ExtensionPairingCodeModel)
        )
        return _pairing_code_from_model(result.scalar_one())


class PostgresExtensionDeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        device_id: ExtensionDeviceId,
    ) -> ExtensionDevice | None:
        result = await self._session.execute(
            select(ExtensionDeviceModel)
            .where(
                ExtensionDeviceModel.workspace_id == workspace_id,
                ExtensionDeviceModel.device_id == device_id,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _device_from_model(model) if model else None

    async def list_by_workspace_and_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> tuple[ExtensionDevice, ...]:
        result = await self._session.execute(
            select(ExtensionDeviceModel)
            .where(
                ExtensionDeviceModel.workspace_id == workspace_id,
                ExtensionDeviceModel.user_id == user_id,
            )
            .order_by(ExtensionDeviceModel.created_at.desc())
        )
        return _devices_from_models(result.scalars().all())

    async def count_active_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ExtensionDeviceModel)
            .where(
                ExtensionDeviceModel.workspace_id == workspace_id,
                ExtensionDeviceModel.user_id == user_id,
                ExtensionDeviceModel.revoked_at.is_(None),
            )
        )
        return int(result.scalar_one())

    async def save(self, device: ExtensionDevice) -> ExtensionDevice:
        values = _device_to_values(device)
        updates = dict(values)
        updates.pop("device_id")
        result = await self._session.execute(
            insert(ExtensionDeviceModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["device_id"], set_=updates)
            .returning(ExtensionDeviceModel)
        )
        return _device_from_model(result.scalar_one())


def _pairing_code_to_values(pairing_code: ExtensionPairingCode) -> dict[str, object]:
    return {
        "pairing_code_id": pairing_code.pairing_code_id,
        "workspace_id": pairing_code.workspace_id,
        "user_id": pairing_code.user_id,
        "token_hash": pairing_code.token_hash,
        "expires_at": pairing_code.expires_at,
        "claimed_at": pairing_code.claimed_at,
        "revoked_at": pairing_code.revoked_at,
        "created_by_user_id": pairing_code.created_by_user_id,
        "created_at": pairing_code.created_at,
    }


def _pairing_code_from_model(model: ExtensionPairingCodeModel) -> ExtensionPairingCode:
    return ExtensionPairingCode(
        pairing_code_id=model.pairing_code_id,
        workspace_id=model.workspace_id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        claimed_at=model.claimed_at,
        revoked_at=model.revoked_at,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
    )


def _device_to_values(device: ExtensionDevice) -> dict[str, object]:
    return {
        "device_id": device.device_id,
        "workspace_id": device.workspace_id,
        "user_id": device.user_id,
        "device_name": device.device_name,
        "extension_version": device.extension_version,
        "credential_hash": device.credential_hash,
        "created_at": device.created_at,
        "last_seen_at": device.last_seen_at,
        "revoked_at": device.revoked_at,
        "revoked_by_user_id": device.revoked_by_user_id,
        "revocation_reason": device.revocation_reason,
    }


def _device_from_model(model: ExtensionDeviceModel) -> ExtensionDevice:
    return ExtensionDevice(
        device_id=model.device_id,
        workspace_id=model.workspace_id,
        user_id=model.user_id,
        device_name=model.device_name,
        extension_version=model.extension_version,
        credential_hash=model.credential_hash,
        created_at=model.created_at,
        last_seen_at=model.last_seen_at,
        revoked_at=model.revoked_at,
        revoked_by_user_id=model.revoked_by_user_id,
        revocation_reason=model.revocation_reason,
    )


def _devices_from_models(
    models: Sequence[ExtensionDeviceModel],
) -> tuple[ExtensionDevice, ...]:
    return tuple(_device_from_model(model) for model in models)