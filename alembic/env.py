from logging.config import fileConfig

from sqlalchemy import pool
from sqlmodel import SQLModel

from alembic import context

# Import all models so SQLModel.metadata picks them up for autogenerate
from app.models.domain import (  # noqa: F401
    Board,
    DailySummary,
    NewsItem,
    UserFeedback,
    ChatMessage,
    UserPersona,
    UserMemory,
    ArticleOverview,
    Source,
    ModelApiConfig,
    TaskRun,
    ContentCluster,
    BlacklistKeyword,
    FilteredItem,
    DailyReportRefinementSession,
)

from app.core.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use SQLModel's metadata for autogenerate support
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # Convert async aiosqlite URL to synchronous sqlite for Alembic
    url = settings.SQLALCHEMY_DATABASE_URI.replace("+aiosqlite", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy import create_engine

    # Build a synchronous SQLite URL from the async one
    url = settings.SQLALCHEMY_DATABASE_URI.replace("+aiosqlite", "")
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
