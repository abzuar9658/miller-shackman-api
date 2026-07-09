import json
from uuid import UUID

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.ports.messaging import EmailMessage, SMSMessage
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.domain.identity import Workspace
from app.domain.leads import CanonicalLeadRecord, CRMProvider


class FakeCampaignExecutionRepository:
    def __init__(self, config: CampaignExecutionConfig | None) -> None:
        self.config = config

    async def get_by_version_id(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: UUID,
    ) -> CampaignExecutionConfig | None:
        if self.config is None:
            return None
        if self.config.workspace_id != workspace_id:
            return None
        if self.config.campaign_version_id != campaign_version_id:
            return None
        return self.config


class FakeWorkspaceRepository:
    def __init__(self, workspace: Workspace | None) -> None:
        self.workspace = workspace

    async def get_by_id(self, workspace_id: WorkspaceId) -> Workspace | None:
        if self.workspace and self.workspace.workspace_id == workspace_id:
            return self.workspace
        return None

    async def save(self, workspace: Workspace) -> Workspace:
        self.workspace = workspace
        return workspace


class FakeWorkspaceContactPolicyRepository:
    def __init__(self, policy: WorkspaceContactPolicy | None) -> None:
        self.policy = policy
        self.saved: list[WorkspaceContactPolicy] = []

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceContactPolicy | None:
        if self.policy is None:
            return None
        if self.policy.workspace_id != workspace_id:
            return None
        return self.policy

    async def save(self, policy: WorkspaceContactPolicy) -> WorkspaceContactPolicy:
        self.saved.append(policy)
        self.policy = policy
        return policy


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        if self.lead and self.lead.workspace_id == workspace_id and self.lead.lead_id == lead_id:
            return self.lead
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeOutboundMessageRepository:
    def __init__(self) -> None:
        self.messages_by_idempotency_key: dict[tuple[WorkspaceId, str], OutboundMessage] = {}
        self.saved: list[OutboundMessage] = []

    async def get_by_id(
        self, workspace_id: WorkspaceId, message_id: UUID
    ) -> OutboundMessage | None:
        for message in self.messages_by_idempotency_key.values():
            if message.workspace_id == workspace_id and message.message_id == message_id:
                return message
        return None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return self.messages_by_idempotency_key.get((workspace_id, idempotency_key))

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.saved.append(message)
        self.messages_by_idempotency_key[(message.workspace_id, message.idempotency_key)] = message
        return message


class FakeLLMClient:
    def __init__(
        self, *, body: str = "Hi — just checking in.", subject: str | None = "Quick check-in"
    ) -> None:
        self.requests: list[LLMCompletionRequest] = []
        self._text = json.dumps(
            {
                "body": body,
                "subject": subject,
                "confidence": 0.91,
                "personalization_notes": ["Used safe canonical context."],
                "safety_flags": [],
            }
        )

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self._text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeSMSProvider:
    def __init__(self, result: str | Exception = "SM123") -> None:
        self.result = result
        self.messages: list[SMSMessage] = []

    async def send(self, message: SMSMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEmailProvider:
    def __init__(self, result: str | Exception = "msg-123") -> None:
        self.result = result
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result
