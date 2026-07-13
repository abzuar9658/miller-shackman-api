from typing import Protocol
from uuid import UUID

from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import Handoff, InboundMessage
from app.domain.identity import User
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowTransition


class LeadReadLeadRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalLeadRecord, ...]:
        raise NotImplementedError


class LeadReadWorkflowRepository(Protocol):
    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        raise NotImplementedError

    async def list_latest_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError


class LeadReadWorkflowTransitionRepository(Protocol):
    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        raise NotImplementedError


class LeadReadInboundMessageRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        raise NotImplementedError


class LeadReadOutboundMessageRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        raise NotImplementedError


class LeadReadHandoffRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError


class LeadReadUserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None:
        raise NotImplementedError
