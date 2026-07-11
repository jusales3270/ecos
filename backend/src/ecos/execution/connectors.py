"""Connector ports and deterministic in-memory connectors for Execution."""

from abc import ABC, abstractmethod
from uuid import UUID

from ecos.execution.models import (
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorHealth,
    ConnectorInvocation,
    ConnectorResult,
    ExecutionArtifact,
    ExecutionStepStatus,
    ExecutionType,
    utc_now,
)


class ExecutionConnector(ABC):
    """Port that all operational connectors must implement."""

    @property
    @abstractmethod
    def descriptor(self) -> ConnectorDescriptor:
        """Return a safe descriptor."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, invocation: ConnectorInvocation) -> ConnectorResult:
        """Execute a connector invocation."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self, invocation: ConnectorInvocation) -> ConnectorResult:
        """Execute a rollback invocation."""
        raise NotImplementedError

    @abstractmethod
    def validate_target(self, target: str | None) -> bool:
        """Validate the declared target without external side effects."""
        raise NotImplementedError

    @property
    def safe_descriptor(self) -> ConnectorDescriptor:
        """Expose the public safe descriptor."""
        return self.descriptor


class InMemoryConnector(ExecutionConnector):
    """Deterministic connector used by tests and default dry-run wiring."""

    def __init__(
        self,
        descriptor: ConnectorDescriptor,
        *,
        fail: bool = False,
        recoverable: bool = False,
        artifact: bool = False,
    ) -> None:
        self._descriptor = descriptor
        self._fail = fail
        self._recoverable = recoverable
        self._artifact = artifact
        self.invocations: list[ConnectorInvocation] = []
        self.rollbacks: list[ConnectorInvocation] = []

    @property
    def descriptor(self) -> ConnectorDescriptor:
        return self._descriptor

    async def execute(self, invocation: ConnectorInvocation) -> ConnectorResult:
        self.invocations.append(invocation)
        if self._fail:
            return ConnectorResult(
                connector_id=self.descriptor.connector_id,
                step_id=invocation.step_id,
                status=ExecutionStepStatus.FAILED,
                recoverable=self._recoverable,
                safe_message="in-memory connector failure",
            )
        artifacts: tuple[ExecutionArtifact, ...] = ()
        if self._artifact:
            artifacts = (
                ExecutionArtifact(
                    artifact_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                    execution_id=invocation.execution_id,
                    step_id=invocation.step_id,
                    type="reference",
                    name="dry-run-artifact",
                    content_reference=(
                        f"memory://{invocation.execution_id}/{invocation.step_id}"
                    ),
                    checksum="dry-run",
                    created_at=utc_now(),
                ),
            )
        return ConnectorResult(
            connector_id=self.descriptor.connector_id,
            step_id=invocation.step_id,
            status=ExecutionStepStatus.COMPLETED,
            output={
                "mode": invocation.mode.value,
                "action": invocation.action,
                "connector_id": self.descriptor.connector_id,
            },
            artifacts=artifacts,
            metrics={"cost_units": 0.0},
        )

    async def rollback(self, invocation: ConnectorInvocation) -> ConnectorResult:
        self.rollbacks.append(invocation)
        return ConnectorResult(
            connector_id=self.descriptor.connector_id,
            step_id=invocation.step_id,
            status=ExecutionStepStatus.ROLLED_BACK,
            output={
                "mode": invocation.mode.value,
                "action": invocation.action,
                "connector_id": self.descriptor.connector_id,
            },
            metrics={"cost_units": 0.0},
        )

    def validate_target(self, target: str | None) -> bool:
        return target is None or bool(target.strip())


def default_in_memory_connector() -> InMemoryConnector:
    """Create the safe default connector used by application wiring."""
    return InMemoryConnector(
        ConnectorDescriptor(
            connector_id="memory.dry_run",
            connector_type="in_memory",
            supported_execution_types=(
                ExecutionType.SYSTEM,
                ExecutionType.API,
                ExecutionType.AGENT,
                ExecutionType.BROWSER,
                ExecutionType.MCP,
            ),
            capabilities=(ConnectorCapability(name="dry_run"),),
            available=True,
            health=ConnectorHealth.HEALTHY,
            supports_dry_run=True,
            supports_live=False,
            supports_idempotency=True,
            supports_rollback=True,
            priority=100,
        )
    )
