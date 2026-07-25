from collections.abc import Collection

from app.application.ports.crm import CRMClient
from app.domain.common.ids import WorkspaceId


async def remove_conflicting_crm_tag_if_present(
    *,
    crm_client: CRMClient,
    workspace_id: WorkspaceId,
    crm_lead_id: str,
    existing_tags: Collection[str] | None,
    active_tag: str | None,
    conflicting_tag: str | None,
) -> None:
    if conflicting_tag is None or conflicting_tag == active_tag:
        return
    if existing_tags is not None and conflicting_tag not in existing_tags:
        return
    await crm_client.remove_tag(workspace_id, crm_lead_id, conflicting_tag)