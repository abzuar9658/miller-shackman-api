from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.compliance.contactability import WorkspaceContactPolicy


def build_pre_send_policy(
    workspace_contact_policy: WorkspaceContactPolicy,
    timezone: str,
) -> PreSendPolicy:
    if not workspace_contact_policy.quiet_hours_enabled:
        return PreSendPolicy(
            allowed_send_start_hour=0,
            allowed_send_end_hour=24,
            timezone=timezone,
        )

    quiet_hours_start = workspace_contact_policy.quiet_hours_start
    quiet_hours_end = workspace_contact_policy.quiet_hours_end
    return PreSendPolicy(
        allowed_send_start_hour=quiet_hours_start.hour if quiet_hours_start else 10,
        allowed_send_end_hour=quiet_hours_end.hour if quiet_hours_end else 17,
        timezone=timezone,
    )