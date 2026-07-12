"""Central SQLAlchemy configuration for ECOS persistence adapters."""

from sqlalchemy import pool, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ecos.core.settings import Settings


def create_database_engine(
    database_url: str, settings: Settings | None = None
) -> AsyncEngine:
    """Create an async SQLAlchemy engine without opening a connection."""
    config = settings or Settings()
    connect_args = {
        "timeout": config.database_connect_timeout_seconds,
        "server_settings": {
            "statement_timeout": str(config.database_statement_timeout_ms),
            "lock_timeout": str(config.database_lock_timeout_ms),
        },
    }
    return create_async_engine(
        database_url,
        poolclass=pool.NullPool,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async database session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping_database(engine: AsyncEngine) -> bool:
    """Run a short transactional database ping."""
    try:
        async with engine.begin() as connection:
            await connection.execute(text("select 1"))
    except SQLAlchemyError:
        return False
    return True
