from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def _execute_if_supported(
    session: object,
    statement: object,
    params: Mapping[str, object] | None = None,
) -> None:
    execute = getattr(session, "execute", None)
    if execute is None:
        return
    await cast(Callable[..., Awaitable[Any]], execute)(statement, params)


async def set_postgres_workspace_context(session: object, workspace_id: str) -> None:
    await _execute_if_supported(
        session,
        text(
            "select set_config('app.current_workspace_id', :workspace_id, true), "
            "set_config('app.service_access', 'off', true)"
        ),
        {"workspace_id": str(workspace_id)},
    )


async def enable_postgres_service_access(session: object) -> None:
    await _execute_if_supported(
        session,
        text(
            "select set_config('app.service_access', 'on', true), "
            "set_config('app.current_workspace_id', '', true)"
        )
    )


async def clear_postgres_rls_context(session: object) -> None:
    await _execute_if_supported(
        session,
        text(
            "select set_config('app.service_access', 'off', true), "
            "set_config('app.current_workspace_id', '', true)"
        )
    )
