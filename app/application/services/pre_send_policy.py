from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.compliance.contactability import WorkspaceContactPolicy

# Frequency limiting is per channel: a recent email must not block an SMS and
# vice versa. Repeat outreach on the same channel stays blocked for 24 hours.
SAME_CHANNEL_FREQUENCY_LIMIT_HOURS = 24


def build_pre_send_policy(
    workspace_contact_policy: WorkspaceContactPolicy,
    timezone: str,
) -> PreSendPolicy:
    if not workspace_contact_policy.quiet_hours_enabled:
        return PreSendPolicy(
            allowed_send_start_hour=0,
            allowed_send_end_hour=24,
            global_frequency_limit_hours=None,
            channel_frequency_limit_hours=SAME_CHANNEL_FREQUENCY_LIMIT_HOURS,
            timezone=timezone,
        )

    quiet_hours_start = workspace_contact_policy.quiet_hours_start
    quiet_hours_end = workspace_contact_policy.quiet_hours_end
    return PreSendPolicy(
        allowed_send_start_hour=quiet_hours_start.hour if quiet_hours_start else 10,
        allowed_send_end_hour=quiet_hours_end.hour if quiet_hours_end else 17,
        global_frequency_limit_hours=None,
        channel_frequency_limit_hours=SAME_CHANNEL_FREQUENCY_LIMIT_HOURS,
        timezone=timezone,
    )