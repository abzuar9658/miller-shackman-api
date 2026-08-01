from datetime import datetime

from pydantic import BaseModel, Field


class AttentionAcknowledgementRequest(BaseModel):
    item_version: str = Field(min_length=1, max_length=500)


class AttentionAcknowledgementResponse(BaseModel):
    item_id: str
    item_version: str
    acknowledged_at: datetime


class AttentionAcknowledgementListResponse(BaseModel):
    status: str
    acknowledgements: list[AttentionAcknowledgementResponse]


class AttentionAcknowledgementResultResponse(BaseModel):
    status: str
    acknowledgement: AttentionAcknowledgementResponse | None = None


class ClearAttentionAcknowledgementResponse(BaseModel):
    status: str
    item_id: str
