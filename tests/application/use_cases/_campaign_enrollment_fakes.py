from uuid import UUID

from app.domain.campaigns.enrollment import CampaignEnrollment
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workflows import LeadWorkflow, WorkflowTransition


class FakeCampaignEnrollmentRepository:
    def __init__(self) -> None:
        self.enrollments: dict[tuple[WorkspaceId, LeadId, UUID], CampaignEnrollment] = {}

    async def get_by_lead_and_campaign(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_id: UUID,
    ) -> CampaignEnrollment | None:
        return self.enrollments.get((workspace_id, lead_id, campaign_id))

    async def save(self, enrollment: CampaignEnrollment) -> CampaignEnrollment:
        self.enrollments[(enrollment.workspace_id, enrollment.lead_id, enrollment.campaign_id)] = (
            enrollment
        )
        return enrollment


class FakeLeadWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, LeadWorkflow] = {}
        self.latest_by_lead: dict[tuple[WorkspaceId, LeadId], LeadWorkflow] = {}

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        return self.latest_by_lead.get((workspace_id, lead_id))

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        return self.latest_by_lead.get((workspace_id, lead_id))

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflows[workflow.workflow_id] = workflow
        self.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
        return workflow


class FakeWorkflowTransitionRepository:
    def __init__(self) -> None:
        self.transitions: dict[UUID, WorkflowTransition] = {}

    async def append(self, transition: WorkflowTransition) -> WorkflowTransition:
        self.transitions[transition.transition_id] = transition
        return transition

    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        return tuple(
            transition
            for transition in self.transitions.values()
            if transition.workspace_id == workspace_id and transition.workflow_id == workflow_id
        )


class FakeTemporalWorkflowStarter:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.always_fail = always_fail

    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        temporal_workflow_id: str,
    ) -> None:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "lead_id": lead_id,
                "temporal_workflow_id": temporal_workflow_id,
            }
        )
        if self.always_fail:
            raise RuntimeError("Temporal start failed")
