"""Deterministic connector registry for Execution."""

from ecos.execution.connectors import ExecutionConnector
from ecos.execution.exceptions import (
    ConnectorDuplicateError,
    ConnectorIncompatibleError,
    ConnectorNotRegisteredError,
    ConnectorUnavailableError,
)
from ecos.execution.models import ExecutionAuthorization, ExecutionMode, ExecutionStep


class ConnectorRegistry:
    """In-memory registry injected into ExecutionEngine."""

    def __init__(self) -> None:
        self._connectors: dict[str, ExecutionConnector] = {}

    def register(self, connector: ExecutionConnector) -> None:
        descriptor = connector.safe_descriptor
        connector_id = descriptor.connector_id
        if connector_id in self._connectors:
            raise ConnectorDuplicateError(f"duplicate connector: {connector_id}")
        self._connectors[connector_id] = connector

    def get(self, connector_id: str) -> ExecutionConnector:
        connector = self._connectors.get(connector_id)
        if connector is None:
            raise ConnectorNotRegisteredError(
                f"connector not registered: {connector_id}"
            )
        return connector

    def by_execution_type(self, execution_type: str) -> tuple[ExecutionConnector, ...]:
        return tuple(
            connector
            for connector in self._connectors.values()
            if any(
                item.value == execution_type
                for item in connector.safe_descriptor.supported_execution_types
            )
        )

    def by_capability(self, capability: str) -> tuple[ExecutionConnector, ...]:
        return tuple(
            connector
            for connector in self._connectors.values()
            if any(
                item.name == capability
                for item in connector.safe_descriptor.capabilities
            )
        )

    def select(
        self,
        step: ExecutionStep,
        authorization: ExecutionAuthorization,
        mode: ExecutionMode,
        *,
        fallback_ids: tuple[str, ...] = (),
    ) -> ExecutionConnector:
        """Select a compatible authorized connector deterministically."""
        candidates: list[ExecutionConnector] = []
        if step.connector_id is not None and not fallback_ids:
            candidates = [self.get(step.connector_id)]
        elif fallback_ids:
            candidates = [self.get(connector_id) for connector_id in fallback_ids]
        elif step.required_capability is not None:
            candidates = list(self.by_capability(step.required_capability))
        if not candidates:
            raise ConnectorNotRegisteredError("no connector candidate available")
        authorized = [
            connector
            for connector in candidates
            if self._is_authorized(connector, authorization)
            and self._is_compatible(connector, step, mode)
        ]
        if not authorized:
            raise ConnectorIncompatibleError("no authorized compatible connector")
        authorized.sort(
            key=lambda item: (
                item.safe_descriptor.priority,
                item.safe_descriptor.connector_id,
            )
        )
        return authorized[0]

    def _is_authorized(
        self,
        connector: ExecutionConnector,
        authorization: ExecutionAuthorization,
    ) -> bool:
        descriptor = connector.safe_descriptor
        if authorization.allowed_connector_ids and (
            descriptor.connector_id not in authorization.allowed_connector_ids
        ):
            return False
        allowed_capabilities = set(authorization.allowed_capabilities)
        if allowed_capabilities and not {
            capability.name for capability in descriptor.capabilities
        }.intersection(allowed_capabilities):
            return False
        return True

    def _is_compatible(
        self,
        connector: ExecutionConnector,
        step: ExecutionStep,
        mode: ExecutionMode,
    ) -> bool:
        descriptor = connector.safe_descriptor
        if not descriptor.available or descriptor.health.value == "unavailable":
            raise ConnectorUnavailableError("connector unavailable")
        if step.execution_type not in descriptor.supported_execution_types:
            return False
        if mode is ExecutionMode.DRY_RUN and not descriptor.supports_dry_run:
            return False
        if mode is ExecutionMode.LIVE and not descriptor.supports_live:
            return False
        if step.required_capability and not any(
            capability.name == step.required_capability
            for capability in descriptor.capabilities
        ):
            return False
        return True
