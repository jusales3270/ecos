"""Persistent login throttling and deterministic API rate limiting."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, delete
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def utc_now() -> datetime:
    return datetime.now(UTC)


def safe_hash(*parts: object) -> str:
    material = "\x1f".join(
        "" if part is None else str(part).strip().lower() for part in parts
    )
    return sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int
    reset_at: datetime


class LoginThrottleRecord(Base):
    """Persistent normalized login throttle state."""

    __tablename__ = "security_login_throttle"

    scope_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    failures: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RateLimitWindowRecord(Base):
    """Persistent fixed-window rate limit counter."""

    __tablename__ = "api_rate_limit_windows"

    scope_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_group: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class InMemorySecurityControlRepository:
    """Thread-safe local/test implementation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._login: dict[str, tuple[int, datetime, datetime | None]] = {}
        self._limits: dict[str, tuple[int, datetime, datetime]] = {}

    def check_login(self, scope_hash: str, *, window: timedelta) -> LimitDecision:
        now = utc_now()
        with self._lock:
            failures, started, blocked = self._login.get(scope_hash, (0, now, None))
            if started + window <= now:
                failures, started, blocked = 0, now, None
                self._login[scope_hash] = (failures, started, blocked)
            if blocked and blocked > now:
                return LimitDecision(
                    False, int((blocked - now).total_seconds()), 0, blocked
                )
            return LimitDecision(True, 0, max(0, failures), started + window)

    def record_login_failure(
        self,
        scope_hash: str,
        *,
        organization_id: UUID | None,
        window: timedelta,
        limit: int,
        block_for: timedelta,
    ) -> LimitDecision:
        del organization_id
        now = utc_now()
        with self._lock:
            failures, started, blocked = self._login.get(scope_hash, (0, now, None))
            if started + window <= now:
                failures, started, blocked = 0, now, None
            failures += 1
            if failures >= limit:
                blocked = now + block_for * max(1, failures - limit + 1)
            self._login[scope_hash] = (failures, started, blocked)
        return self.check_login(scope_hash, window=window)

    def reset_login(self, scope_hash: str) -> None:
        with self._lock:
            self._login.pop(scope_hash, None)

    def consume_rate_limit(
        self,
        scope_hash: str,
        *,
        route_group: str,
        limit: int,
        window: timedelta,
    ) -> LimitDecision:
        now = utc_now()
        with self._lock:
            count, started, expires = self._limits.get(
                scope_hash, (0, now, now + window)
            )
            if expires <= now:
                count, started, expires = 0, now, now + window
            count += 1
            self._limits[scope_hash] = (count, started, expires)
        allowed = count <= limit
        return LimitDecision(
            allowed,
            0 if allowed else max(1, int((expires - now).total_seconds())),
            max(0, limit - count),
            expires,
        )

    def cleanup(self) -> int:
        now = utc_now()
        with self._lock:
            before = len(self._limits)
            self._limits = {
                key: value for key, value in self._limits.items() if value[2] > now
            }
            return before - len(self._limits)


class PostgresSecurityControlRepository:
    """PostgreSQL-backed login throttle and rate limiter."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)

    def check_login(self, scope_hash: str, *, window: timedelta) -> LimitDecision:
        return _run(self._check_login(scope_hash, window=window))

    async def _check_login(
        self, scope_hash: str, *, window: timedelta
    ) -> LimitDecision:
        now = utc_now()
        async with self._session_factory() as database:
            row = await database.get(LoginThrottleRecord, scope_hash)
            if row is None or row.window_started_at + window <= now:
                return LimitDecision(True, 0, 0, now + window)
            if row.blocked_until and row.blocked_until > now:
                return LimitDecision(
                    False,
                    int((row.blocked_until - now).total_seconds()),
                    0,
                    row.blocked_until,
                )
            return LimitDecision(True, 0, row.failures, row.window_started_at + window)

    def record_login_failure(
        self,
        scope_hash: str,
        *,
        organization_id: UUID | None,
        window: timedelta,
        limit: int,
        block_for: timedelta,
    ) -> LimitDecision:
        return _run(
            self._record_login_failure(
                scope_hash,
                organization_id=organization_id,
                window=window,
                limit=limit,
                block_for=block_for,
            )
        )

    async def _record_login_failure(
        self,
        scope_hash: str,
        *,
        organization_id: UUID | None,
        window: timedelta,
        limit: int,
        block_for: timedelta,
    ) -> LimitDecision:
        now = utc_now()
        async with self._session_factory() as database:
            row = await database.get(
                LoginThrottleRecord, scope_hash, with_for_update=True
            )
            if row is None:
                row = LoginThrottleRecord(
                    scope_hash=scope_hash,
                    organization_id=organization_id,
                    failures=0,
                    window_started_at=now,
                    blocked_until=None,
                    updated_at=now,
                )
                database.add(row)
            if row.window_started_at + window <= now:
                row.failures = 0
                row.window_started_at = now
                row.blocked_until = None
            row.failures += 1
            row.organization_id = organization_id
            row.updated_at = now
            if row.failures >= limit:
                row.blocked_until = now + block_for * max(1, row.failures - limit + 1)
            await database.commit()
        return self.check_login(scope_hash, window=window)

    def reset_login(self, scope_hash: str) -> None:
        _run(self._reset_login(scope_hash))

    async def _reset_login(self, scope_hash: str) -> None:
        async with self._session_factory() as database:
            await database.execute(
                delete(LoginThrottleRecord).where(
                    LoginThrottleRecord.scope_hash == scope_hash
                )
            )
            await database.commit()

    def consume_rate_limit(
        self,
        scope_hash: str,
        *,
        route_group: str,
        limit: int,
        window: timedelta,
    ) -> LimitDecision:
        return _run(
            self._consume_rate_limit(
                scope_hash, route_group=route_group, limit=limit, window=window
            )
        )

    async def _consume_rate_limit(
        self, scope_hash: str, *, route_group: str, limit: int, window: timedelta
    ) -> LimitDecision:
        now = utc_now()
        async with self._session_factory() as database:
            row = await database.get(
                RateLimitWindowRecord, scope_hash, with_for_update=True
            )
            if row is None or row.expires_at <= now:
                row = RateLimitWindowRecord(
                    scope_hash=scope_hash,
                    route_group=route_group,
                    window_started_at=now,
                    count=0,
                    expires_at=now + window,
                )
                await database.merge(row)
            row.count += 1
            row.route_group = route_group
            await database.commit()
            allowed = row.count <= limit
            return LimitDecision(
                allowed,
                0 if allowed else max(1, int((row.expires_at - now).total_seconds())),
                max(0, limit - row.count),
                row.expires_at,
            )

    def cleanup(self) -> int:
        return _run(self._cleanup())

    async def _cleanup(self) -> int:
        async with self._session_factory() as database:
            result = await database.execute(
                delete(RateLimitWindowRecord).where(
                    RateLimitWindowRecord.expires_at <= utc_now()
                )
            )
            await database.commit()
            return int(result.rowcount or 0)
