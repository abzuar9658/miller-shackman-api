import math
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.crm_history_imports import (
    CrmHistoryImportDirection,
    CrmHistoryScalar,
)

_MAX_DETAILS_ITEMS = 50
_MAX_DETAILS_KEY_LENGTH = 128
_MAX_DETAILS_STRING_LENGTH = 1_000
_MAX_DETAILS_NUMBER_MAGNITUDE = 1_000_000_000_000_000


class CreateCrmHistoryImportRequest(BaseModel):
    lead_id: UUID


class CrmHistoryImportEventRequest(BaseModel):
    external_activity_id: str | None = Field(default=None, max_length=255)
    fingerprint: str = Field(min_length=1, max_length=128)
    activity_type: str = Field(min_length=1, max_length=100)
    direction: CrmHistoryImportDirection | None = None
    content: str | None = Field(default=None, max_length=100_000)
    occurred_at: datetime
    actor_agent_id: str | None = Field(default=None, max_length=255)
    actor_name: str | None = Field(default=None, max_length=255)
    details: dict[str, CrmHistoryScalar] = Field(
        default_factory=dict, max_length=_MAX_DETAILS_ITEMS
    )

    @field_validator("fingerprint", "activity_type")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("external_activity_id", "actor_agent_id", "actor_name")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def details_must_be_bounded_scalars(self) -> Self:
        for key, value in self.details.items():
            if not key.strip() or len(key) > _MAX_DETAILS_KEY_LENGTH:
                raise ValueError("details keys must be nonblank and at most 128 characters")
            if isinstance(value, str) and len(value) > _MAX_DETAILS_STRING_LENGTH:
                raise ValueError("details string values must be at most 1000 characters")
            if isinstance(value, bool) or value is None or isinstance(value, str):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("details numeric values must be finite")
            if abs(value) > _MAX_DETAILS_NUMBER_MAGNITUDE:
                raise ValueError("details numeric values are too large")
        return self


class IngestCrmHistoryEventsRequest(BaseModel):
    events: list[CrmHistoryImportEventRequest] = Field(max_length=100)


class ExtensionExportCrmHistoryRequest(BaseModel):
    crm_lead_id: str = Field(min_length=1, max_length=255)
    events: list[CrmHistoryImportEventRequest] = Field(default_factory=list, max_length=1000)
    source_payload: dict[str, Any] | None = None
    source_url: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def source_or_events_required(self) -> Self:
        if not self.events and self.source_payload is None:
            raise ValueError("events or source_payload is required")
        return self


class CrmHistoryImportJobResponse(BaseModel):
    job_id: UUID
    workspace_id: UUID
    lead_id: UUID
    crm_lead_id: str
    status: str
    received_count: int
    promoted_count: int
    duplicate_count: int
    rejected_count: int
    failure_reason: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class CrmHistoryImportCapabilityResponse(BaseModel):
    enabled: bool
    allowed: bool
    reasons: list[str]


class CreateCrmHistoryImportResponse(BaseModel):
    status: str
    job: CrmHistoryImportJobResponse
    upload_token: str


class CrmHistoryImportReadResponse(BaseModel):
    status: str
    job: CrmHistoryImportJobResponse


class IngestCrmHistoryEventsResponse(BaseModel):
    status: str
    accepted_count: int
    duplicate_count: int
    rejected_count: int
    job: CrmHistoryImportJobResponse
