from logging.config import fileConfig
from typing import Any

from alembic.ddl.impl import DefaultImpl
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    engine_from_config,
    inspect,
    pool,
    text,
)

from alembic import context
from app.core.config import get_settings
from app.infrastructure.persistence.postgres.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_migration_url)

target_metadata = Base.metadata

_VERSION_TABLE_NAME = config.get_main_option("version_table") or "alembic_version"
_VERSION_TABLE_SCHEMA = config.get_main_option("version_table_schema") or None
_VERSION_TABLE_COLUMN = "version_num"
_LONG_REVISION_LENGTH = 255


def _long_revision_version_table_impl(
    self: DefaultImpl,
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **kw: Any,
) -> Table:
    table = Table(
        version_table,
        MetaData(),
        Column("version_num", String(255), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        table.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"),
        )
    return table


def _repair_legacy_version_table(connection: Any) -> None:
    inspector = inspect(connection)
    if not inspector.has_table(_VERSION_TABLE_NAME, schema=_VERSION_TABLE_SCHEMA):
        return

    columns = inspector.get_columns(_VERSION_TABLE_NAME, schema=_VERSION_TABLE_SCHEMA)
    version_column = next(
        (column for column in columns if column["name"] == _VERSION_TABLE_COLUMN),
        None,
    )
    if version_column is None:
        return

    current_length = getattr(version_column["type"], "length", None)
    if current_length is None or current_length >= _LONG_REVISION_LENGTH:
        return

    table_name = _qualified_table_name(connection)
    column_name = connection.dialect.identifier_preparer.quote_identifier(_VERSION_TABLE_COLUMN)
    connection.execute(
        text(
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
            f"TYPE VARCHAR({_LONG_REVISION_LENGTH})"
        )
    )


def _qualified_table_name(connection: Any) -> str:
    quote_identifier = connection.dialect.identifier_preparer.quote_identifier
    table_name = str(quote_identifier(_VERSION_TABLE_NAME))
    if _VERSION_TABLE_SCHEMA is None:
        return table_name
    schema_name = str(quote_identifier(_VERSION_TABLE_SCHEMA))
    return f"{schema_name}.{table_name}"


# Alembic defaults the version table column to VARCHAR(32), but this repository
# uses descriptive revision identifiers longer than 32 characters.
DefaultImpl.version_table_impl = _long_revision_version_table_impl  # type: ignore[method-assign]


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _repair_legacy_version_table(connection)
        if connection.in_transaction():
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
