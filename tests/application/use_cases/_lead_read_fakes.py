from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.conversations import Handoff, InboundMessage
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowTransition


class FakeLeadRepository:
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        self._leads = {(lead.workspace_id, lead.lead_id): lead for lead in leads}

    async def get_by_id(self, workspace_id: object, lead_id: object):
        return self._leads.get((workspace_id, lead_id))

    async def list_for_workspace(self, workspace_id: object, *, limit: int = 100):
        return tuple(lead for (wid, _), lead in self._leads.items() if wid == workspace_id)[:limit]


class FakeLeadWorkflowRepository:
    def __init__(self, workflows: tuple[LeadWorkflow, ...]) -> None:
        self._latest = {
            (workflow.workspace_id, workflow.lead_id): workflow for workflow in workflows
        }

    async def get_latest_for_lead(self, workspace_id: object, lead_id: object):
        return self._latest.get((workspace_id, lead_id))

    async def list_latest_for_workspace(self, workspace_id: object, *, limit: int = 100):
        return tuple(wf for (wid, _), wf in self._latest.items() if wid == workspace_id)[:limit]


class FakeWorkflowTransitionRepository:
    def __init__(self, transitions: tuple[WorkflowTransition, ...]) -> None:
        self._items = transitions

    async def list_for_workflow(self, workspace_id: object, workflow_id: object, limit: int = 100):
        return tuple(
            item
            for item in self._items
            if item.workspace_id == workspace_id and item.workflow_id == workflow_id
        )[:limit]


class FakeInboundMessageRepository:
    def __init__(self, messages: tuple[InboundMessage, ...]) -> None:
        self._messages = messages

    async def list_for_lead(self, workspace_id: object, lead_id: object, *, limit: int = 100):
        return tuple(
            item
            for item in self._messages
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeOutboundMessageRepository:
    def __init__(self, messages: tuple[OutboundMessage, ...]) -> None:
        self._messages = messages

    async def list_for_lead(self, workspace_id: object, lead_id: object, *, limit: int = 100):
        return tuple(
            item
            for item in self._messages
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeHandoffRepository:
    def __init__(self, handoffs: tuple[Handoff, ...]) -> None:
        self._handoffs = handoffs

    async def list_handoffs(self, workspace_id: object, *, limit: int = 100):
        return tuple(item for item in self._handoffs if item.workspace_id == workspace_id)[:limit]

    async def list_for_lead(self, workspace_id: object, lead_id: object, *, limit: int = 100):
        return tuple(
            item
            for item in self._handoffs
            if item.workspace_id == workspace_id and item.lead_id == lead_id
        )[:limit]


class FakeUserRepository:
    def __init__(self, users: dict[object, object]) -> None:
        self._users = users

    async def get_by_id(self, user_id: object):
        return self._users.get(user_id)
