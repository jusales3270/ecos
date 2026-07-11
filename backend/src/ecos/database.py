"""Central SQLAlchemy configuration for ECOS persistence adapters."""

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine without opening a connection."""
    # The public repository contract is synchronous and creates a loop per call.
    return create_async_engine(database_url, poolclass=pool.NullPool)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async database session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)
