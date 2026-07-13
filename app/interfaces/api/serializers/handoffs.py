from app.domain.conversations import Handoff
from app.interfaces.api.schemas.handoffs import HandoffResponse


def handoff_response(handoff: Handoff) -> HandoffResponse:
    return HandoffResponse(
        handoff_id=handoff.handoff_id,
        workspace_id=handoff.workspace_id,
        lead_id=handoff.lead_id,
        campaign_id=handoff.campaign_id,
        workflow_id=handoff.workflow_id,
        conversation_id=handoff.conversation_id,
        inbound_message_id=handoff.inbound_message_id,
        assigned_agent_user_id=handoff.assigned_agent_user_id,
        assigned_agent_crm_id=handoff.assigned_agent_crm_id,
        reason_code=handoff.reason_code.value,
        summary=handoff.summary,
        latest_inbound_text=handoff.latest_inbound_text,
        preferences=dict(handoff.preferences),
        status=handoff.status.value,
        created_at=handoff.created_at,
        notified_at=handoff.notified_at,
        acknowledged_at=handoff.acknowledged_at,
    )
