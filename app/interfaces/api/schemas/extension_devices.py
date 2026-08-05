from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ClaimExtensionDeviceRequest(BaseModel):
    setup_code: str = Field(min_length=1, max_length=500)
    device_name: str = Field(min_length=1, max_length=100)
    extension_version: str | None = Field(default=None, max_length=32)

    @field_validator("setup_code", "device_name")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("extension_version")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ExtensionDeviceResponse(BaseModel):
    device_id: UUID
    workspace_id: UUID
    user_id: UUID
    device_name: str
    extension_version: str | None
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    revoked_by_user_id: UUID | None
    revocation_reason: str | None


class CreateExtensionPairingCodeResponse(BaseModel):
    pairing_code_id: UUID
    workspace_id: UUID
    user_id: UUID
    setup_code: str
    expires_at: datetime


class ClaimExtensionDeviceResponse(BaseModel):
    credential: str
    device: ExtensionDeviceResponse


class ListExtensionDevicesResponse(BaseModel):
    devices: list[ExtensionDeviceResponse]