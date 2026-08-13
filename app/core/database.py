from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _server_settings() -> dict[str, str]:
    values = {
        "statement_timeout": settings.database_statement_timeout_ms,
        "idle_in_transaction_session_timeout": (
            settings.database_idle_in_transaction_session_timeout_ms
        ),
        "lock_timeout": settings.database_lock_timeout_ms,
    }
    return {name: str(ms) for name, ms in values.items() if ms > 0}


def _connect_args() -> dict[str, object]:
    server_settings = _server_settings()
    return {"server_settings": server_settings} if server_settings else {}


async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_recycle=settings.database_pool_recycle_seconds,
    connect_args=_connect_args(),
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
        ),
    )


async def clear_postgres_rls_context(session: object) -> None:
    await _execute_if_supported(
        session,
        text(
            "select set_config('app.service_access', 'off', true), "
            "set_config('app.current_workspace_id', '', true)"
        ),
    )
