from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.core.database import set_postgres_workspace_context
from app.domain.identity import (
    AuthenticatedActor,
    WorkspaceMembership,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)


async def require_workspace_membership(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> WorkspaceMembership:
    membership = await bundle.membership_repository.get_by_user_and_workspace(
        actor.user_id,
        workspace_id,
    )
    if membership is None or membership.status != WorkspaceMembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace membership required",
        )
    return membership


async def get_workspace_actor(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
    bundle: Annotated[AuthServiceBundle, Depends(get_auth_service_bundle)],
) -> AuthenticatedActor:
    membership = await require_workspace_membership(
        workspace_id=workspace_id,
        actor=actor,
        bundle=bundle,
    )

    workspace = await bundle.workspace_repository.get_by_id(workspace_id)
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace not active",
        )

    await set_postgres_workspace_context(bundle.session, str(workspace_id))

    if actor.active_workspace_id == workspace_id:
        return actor

    return AuthenticatedActor(
        user_id=actor.user_id,
        user_status=actor.user_status,
        active_role=membership.role,
        active_workspace_id=workspace.workspace_id,
        active_workspace_status=workspace.status,
        active_membership_id=membership.membership_id,
        active_membership_status=membership.status,
    )
