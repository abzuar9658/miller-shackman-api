from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.application.use_cases.extension_devices import (
    ExtensionDeviceReasonCode,
    claim_extension_device,
    create_pairing_code,
    list_extension_devices,
    parse_extension_setup_code,
    revoke_extension_device,
)
from app.core.database import set_postgres_workspace_context
from app.domain.identity import AuthenticatedActor, ExtensionDevice
from app.interfaces.api.dependencies.extension_devices import (
    ExtensionDeviceBundle,
    get_extension_device_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.extension_devices import (
    ClaimExtensionDeviceRequest,
    ClaimExtensionDeviceResponse,
    CreateExtensionPairingCodeResponse,
    ExtensionDeviceResponse,
    ListExtensionDevicesResponse,
)

router = APIRouter(tags=["extension-devices"])
public_router = APIRouter(tags=["extension-auth"])


@router.post(
    "/{workspace_id}/users/{user_id}/extension/pairing-code",
    response_model=CreateExtensionPairingCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_extension_pairing_code_route(
    workspace_id: UUID,
    user_id: UUID,
    response: Response,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ExtensionDeviceBundle, Depends(get_extension_device_bundle)],
) -> CreateExtensionPairingCodeResponse:
    result = await create_pairing_code(
        actor=actor,
        workspace_id=workspace_id,
        target_user_id=user_id,
        user_repository=bundle.user_repository,
        membership_repository=bundle.membership_repository,
        pairing_code_repository=bundle.pairing_code_repository,
        audit_log_repository=bundle.audit_log_repository,
        token_service=bundle.token_service,
        now=datetime.now(UTC),
    )
    if result.pairing_code is None or result.setup_code is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_reasons(result.reasons))
    await bundle.session.commit()
    _prevent_secret_caching(response)
    return CreateExtensionPairingCodeResponse(
        pairing_code_id=result.pairing_code.pairing_code_id,
        workspace_id=result.pairing_code.workspace_id,
        user_id=result.pairing_code.user_id,
        setup_code=result.setup_code,
        expires_at=result.pairing_code.expires_at,
    )


@router.get(
    "/{workspace_id}/users/{user_id}/extension/devices",
    response_model=ListExtensionDevicesResponse,
)
async def list_extension_devices_route(
    workspace_id: UUID,
    user_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ExtensionDeviceBundle, Depends(get_extension_device_bundle)],
) -> ListExtensionDevicesResponse:
    result = await list_extension_devices(
        actor=actor,
        workspace_id=workspace_id,
        target_user_id=user_id,
        device_repository=bundle.device_repository,
    )
    if result.reasons:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_reasons(result.reasons))
    return ListExtensionDevicesResponse(
        devices=[_device_response(device) for device in result.devices]
    )


@router.delete(
    "/{workspace_id}/extension-devices/{device_id}",
    response_model=ExtensionDeviceResponse,
)
async def revoke_extension_device_route(
    workspace_id: UUID,
    device_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[ExtensionDeviceBundle, Depends(get_extension_device_bundle)],
    reason: Annotated[str | None, Query(max_length=500)] = None,
) -> ExtensionDeviceResponse:
    result = await revoke_extension_device(
        actor=actor,
        workspace_id=workspace_id,
        device_id=device_id,
        reason=reason,
        device_repository=bundle.device_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
    )
    if result.device is None:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if ExtensionDeviceReasonCode.DEVICE_NOT_FOUND in result.reasons
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=_reasons(result.reasons))
    await bundle.session.commit()
    return _device_response(result.device)


@public_router.post(
    "/pair",
    response_model=ClaimExtensionDeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def claim_extension_device_route(
    request: ClaimExtensionDeviceRequest,
    response: Response,
    bundle: Annotated[ExtensionDeviceBundle, Depends(get_extension_device_bundle)],
) -> ClaimExtensionDeviceResponse:
    parsed = parse_extension_setup_code(request.setup_code)
    if parsed is None:
        raise _invalid_pairing_code()
    workspace_id, _ = parsed
    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    result = await claim_extension_device(
        setup_code=request.setup_code,
        workspace_id=workspace_id,
        device_name=request.device_name,
        extension_version=request.extension_version,
        pairing_code_repository=bundle.pairing_code_repository,
        device_repository=bundle.device_repository,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        audit_log_repository=bundle.audit_log_repository,
        token_service=bundle.token_service,
        now=datetime.now(UTC),
    )
    if result.device is None or result.credential is None:
        if ExtensionDeviceReasonCode.DEVICE_LIMIT_REACHED in result.reasons:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Maximum active extension devices reached; revoke a device and try again",
            )
        raise _invalid_pairing_code()
    await bundle.session.commit()
    _prevent_secret_caching(response)
    return ClaimExtensionDeviceResponse(
        credential=result.credential,
        device=_device_response(result.device),
    )


def _device_response(device: ExtensionDevice) -> ExtensionDeviceResponse:
    return ExtensionDeviceResponse(
        device_id=device.device_id,
        workspace_id=device.workspace_id,
        user_id=device.user_id,
        device_name=device.device_name,
        extension_version=device.extension_version,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        revoked_by_user_id=device.revoked_by_user_id,
        revocation_reason=device.revocation_reason,
    )


def _invalid_pairing_code() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid extension pairing code",
        headers={"WWW-Authenticate": "PairingCode"},
    )


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _reasons(reasons: tuple[object, ...]) -> list[str]:
    return [str(getattr(reason, "value", reason)) for reason in reasons]