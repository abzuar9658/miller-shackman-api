from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads import (
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
)
from app.infrastructure.persistence.postgres.models import LeadClassificationArtifactModel


class PostgresLeadClassificationArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadClassificationArtifact | None:
        result = await self._session.execute(
            select(LeadClassificationArtifactModel)
            .where(LeadClassificationArtifactModel.workspace_id == workspace_id)
            .where(LeadClassificationArtifactModel.artifact_id == artifact_id)
        )
        model = result.scalar_one_or_none()
        return _model_to_artifact(model) if model is not None else None

    async def save(self, artifact: LeadClassificationArtifact) -> LeadClassificationArtifact:
        model = LeadClassificationArtifactModel(**_artifact_to_values(artifact))
        self._session.add(model)
        await self._session.flush()
        return artifact

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadClassificationArtifact, ...]:
        result = await self._session.execute(
            select(LeadClassificationArtifactModel)
            .where(
                LeadClassificationArtifactModel.workspace_id == workspace_id,
                LeadClassificationArtifactModel.lead_id == lead_id,
            )
            .order_by(LeadClassificationArtifactModel.created_at.desc())
            .limit(limit),
        )
        return tuple(_model_to_artifact(model) for model in result.scalars().all())


def _artifact_to_values(artifact: LeadClassificationArtifact) -> dict[str, object]:
    return {
        "artifact_id": artifact.artifact_id,
        "workspace_id": artifact.workspace_id,
        "lead_id": artifact.lead_id,
        "source": artifact.source,
        "outcome": artifact.outcome.value,
        "pause_reason_code": (
            artifact.pause_reason_code.value if artifact.pause_reason_code else None
        ),
        "reengagement_not_before": artifact.reengagement_not_before,
        "reengagement_window_label": artifact.reengagement_window_label,
        "confidence": artifact.confidence,
        "evidence": list(artifact.evidence),
        "summary": artifact.summary,
        "model": artifact.model,
        "prompt_version": artifact.prompt_version,
        "latency_ms": artifact.latency_ms,
        "usage_tokens": artifact.usage_tokens,
        "prompt_text": artifact.prompt_text,
        "input_context": dict(artifact.input_context),
        "raw_llm_response_text": artifact.raw_llm_response_text,
        "parsed_llm_response": dict(artifact.parsed_llm_response),
        "applied_status": artifact.applied_status.value,
        "applied_at": artifact.applied_at,
        "created_at": artifact.created_at,
    }


def _model_to_artifact(model: LeadClassificationArtifactModel) -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=model.artifact_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        source=model.source,
        outcome=LeadStateClassificationOutcome(model.outcome),
        pause_reason_code=PausedSearchReasonCode(model.pause_reason_code)
        if model.pause_reason_code
        else None,
        reengagement_not_before=model.reengagement_not_before,
        reengagement_window_label=model.reengagement_window_label,
        confidence=model.confidence,
        evidence=tuple(model.evidence),
        summary=model.summary,
        model=model.model,
        prompt_version=model.prompt_version,
        latency_ms=model.latency_ms,
        usage_tokens=model.usage_tokens,
        prompt_text=model.prompt_text,
        input_context=model.input_context,
        raw_llm_response_text=model.raw_llm_response_text,
        parsed_llm_response=model.parsed_llm_response,
        applied_status=LeadClassificationAppliedStatus(model.applied_status),
        applied_at=model.applied_at,
        created_at=model.created_at,
    )
