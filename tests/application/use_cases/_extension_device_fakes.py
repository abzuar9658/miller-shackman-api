from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.domain.identity import ExtensionDevice, ExtensionPairingCode


class FakeExtensionPairingCodeRepository:
    def __init__(self, pairing_codes: tuple[ExtensionPairingCode, ...] = ()) -> None:
        self.pairing_codes = {
            pairing_code.pairing_code_id: pairing_code for pairing_code in pairing_codes
        }

    async def get_by_token_hash_for_update(
        self,
        workspace_id: UUID,
        token_hash: str,
    ) -> ExtensionPairingCode | None:
        return next(
            (
                pairing_code
                for pairing_code in self.pairing_codes.values()
                if pairing_code.workspace_id == workspace_id
                and pairing_code.token_hash == token_hash
            ),
            None,
        )

    async def revoke_pending_for_user(
        self,
        workspace_id: UUID,
        user_id: UUID,
        *,
        revoked_at: datetime,
    ) -> int:
        count = 0
        for pairing_code_id, pairing_code in tuple(self.pairing_codes.items()):
            if (
                pairing_code.workspace_id == workspace_id
                and pairing_code.user_id == user_id
                and pairing_code.claimed_at is None
                and pairing_code.revoked_at is None
            ):
                self.pairing_codes[pairing_code_id] = replace(
                    pairing_code, revoked_at=revoked_at
                )
                count += 1
        return count

    async def save(self, pairing_code: ExtensionPairingCode) -> ExtensionPairingCode:
        self.pairing_codes[pairing_code.pairing_code_id] = pairing_code
        return pairing_code


class FakeExtensionDeviceRepository:
    def __init__(self, devices: tuple[ExtensionDevice, ...] = ()) -> None:
        self.devices = {device.device_id: device for device in devices}

    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        device_id: UUID,
    ) -> ExtensionDevice | None:
        device = self.devices.get(device_id)
        if device is None or device.workspace_id != workspace_id:
            return None
        return device

    async def list_by_workspace_and_user(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> tuple[ExtensionDevice, ...]:
        return tuple(
            device
            for device in self.devices.values()
            if device.workspace_id == workspace_id and device.user_id == user_id
        )

    async def count_active_for_user(self, workspace_id: UUID, user_id: UUID) -> int:
        return sum(
            device.workspace_id == workspace_id
            and device.user_id == user_id
            and device.revoked_at is None
            for device in self.devices.values()
        )

    async def save(self, device: ExtensionDevice) -> ExtensionDevice:
        self.devices[device.device_id] = device
        return device