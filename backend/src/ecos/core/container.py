"""Dependency injection container for ECOS services and fake providers."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ecos.context import ContextEngine, ContextService
from ecos.core.exceptions import ConfigurationError
from ecos.core.settings import Settings
from ecos.database import create_database_engine
from ecos.debate import AIDebateEngine, DebateService
from ecos.decision import AIDecisionSupportEngine, DecisionService
from ecos.domain import Objective, Organization
from ecos.events import EventService
from ecos.execution import (
    ConnectorRegistry,
    ExecutionEngine,
    ExecutionResultRepository,
    InMemoryExecutionResultRepository,
    InMemoryHumanTaskProvider,
    InMemoryIdempotencyProvider,
    default_in_memory_connector,
)
from ecos.execution.postgres_repository import PostgresExecutionResultRepository
from ecos.governance import (
    DefaultApprovalPolicyProvider,
    GovernanceConfig,
    GovernanceEngine,
    InMemoryPolicyProvider,
    demo_policy,
)
from ecos.knowledge import (
    DeterministicSemanticSearchProvider,
    GraphIntegrityService,
    InMemoryKnowledgeGraphRepository,
    KnowledgeContextExpander,
    KnowledgeGraphRepository,
    KnowledgeGraphService,
    KnowledgeLimits,
    KnowledgeProjector,
)
from ecos.knowledge.postgres import PostgresKnowledgeGraphRepository
from ecos.learning import (
    InMemoryLearningRepository,
    LearningRepository,
    LearningService,
    PostgresLearningRepository,
)
from ecos.memory import MemoryRepository, MemoryService, PostgresMemoryRepository
from ecos.observability import (
    AlertProjector,
    AuditProjector,
    EventReplayService,
    InMemoryAuditRepository,
    InMemoryEventStore,
    InMemoryObservabilityRepository,
    MetricProjector,
    ObservabilityService,
    RedactionPolicy,
    SessionTraceReconstructor,
    StructuredLogProjector,
    TraceProjector,
)
from ecos.observability.postgres import (
    PostgresAuditRepository,
    PostgresEventStore,
    PostgresObservabilityRepository,
)
from ecos.observation import (
    InMemoryFeedbackProvider,
    InMemoryMeasurementProvider,
    InMemoryObservationIdempotencyProvider,
    InMemoryObservationRepository,
    ObservationConfig,
    ObservationEngine,
    ObservationRepository,
    PostgresObservationRepository,
)
from ecos.operational import OperationalService
from ecos.operational.postgres import PostgresOperationalRepository
from ecos.operational.repository import (
    InMemoryOperationalRepository,
    OperationalRepository,
)
from ecos.orchestrator import (
    OrchestrationConfig,
    OrchestrationMode,
    Orchestrator,
    OrchestratorService,
)
from ecos.outbox import (
    InMemoryOutboxRepository,
    OutboxService,
    PostgresOutboxRepository,
)
from ecos.planner import CognitivePlanner, PlannerService
from ecos.providers import (
    AIProvider,
    AIService,
    OpenAIProvider,
    ProviderRegistry,
    ProviderStatus,
    ProviderType,
)
from ecos.reasoning import AIReasoningEngine, ReasoningService
from ecos.runtime import (
    AuthenticatedRuntimeService,
    CognitivePipeline,
    FakeAIProvider,
    FakeContextProvider,
    FakeDebateProvider,
    FakeDecisionProvider,
    FakeEventBus,
    FakeMemoryRepository,
    FakeOrchestratorProvider,
    FakePlannerProvider,
    FakeReasoningProvider,
    FakeSessionRepository,
    FakeSpecialistProvider,
    FakeWarEngine,
    InMemoryRuntimeCheckpointRepository,
    PostgresRuntimeCheckpointRepository,
    RuntimeArtifactCodec,
    RuntimeCheckpointRepository,
    RuntimeEngine,
)
from ecos.runtime.adapters import (
    ContextExecutor,
    DebateExecutor,
    DecisionExecutor,
    ExecutionExecutor,
    GovernanceExecutor,
    LearningExecutor,
    ObservationExecutor,
    ReasoningExecutor,
    SimulationExecutor,
    SpecialistsExecutor,
)
from ecos.security import (
    InMemorySecurityRepository,
    Role,
    SecurityIdentityPort,
    SecurityRepository,
    SecurityService,
    TenantScopedMemoryService,
    TenantScopedSessionService,
)
from ecos.security.controls import (
    InMemorySecurityControlRepository,
    PostgresSecurityControlRepository,
)
from ecos.security.postgres import PostgresSecurityRepository
from ecos.session import PostgresSessionRepository, SessionRepository, SessionService
from ecos.simulation import AIWarEngine, SimulationService
from ecos.specialists import (
    Capability,
    Specialist,
    SpecialistRegistry,
    SpecialistService,
    SpecialistType,
)


@dataclass
class Container:
    """Application dependency container for services and fake providers."""

    settings: Settings = field(default_factory=Settings)

    def __post_init__(self) -> None:
        """Register fake providers, repositories, services and runtime engine."""
        organization = Organization(name="ECOS Container Organization")
        objective = Objective(
            organization_id=organization.id,
            title="Container runtime objective",
        )
        self.memory_repository: MemoryRepository
        if self.settings.memory_repository == "postgres":
            self.memory_repository = PostgresMemoryRepository(
                self.settings.database_url
            )
        else:
            self.memory_repository = FakeMemoryRepository()
        self.event_bus = FakeEventBus()
        self.session_repository: SessionRepository
        if self.settings.session_repository == "postgres":
            self.session_repository = PostgresSessionRepository(
                self.settings.database_url
            )
        else:
            self.session_repository = FakeSessionRepository()
        self.runtime_checkpoint_repository: RuntimeCheckpointRepository
        if (
            self.settings.runtime_checkpoint_repository == "postgres"
            or self.settings.session_repository == "postgres"
        ):
            self.runtime_checkpoint_repository = PostgresRuntimeCheckpointRepository(
                self.settings.database_url,
                lease_duration=self.settings.runtime_start_claim_lease,
            )
        else:
            self.runtime_checkpoint_repository = InMemoryRuntimeCheckpointRepository(
                lease_duration=self.settings.runtime_start_claim_lease
            )
        self.planner_provider = FakePlannerProvider()
        self.specialist_provider = FakeSpecialistProvider()
        self.decision_provider = FakeDecisionProvider()
        self.orchestrator_provider = FakeOrchestratorProvider()
        self.ai_provider: AIProvider
        ai_provider_type: ProviderType
        if self.settings.ai_provider == "openai":
            if not self.settings.openai_api_key:
                raise ConfigurationError(
                    "ECOS_OPENAI_API_KEY is required when ECOS_AI_PROVIDER=openai."
                )
            self.ai_provider = OpenAIProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                embedding_model=self.settings.openai_embedding_model,
                timeout_seconds=self.settings.openai_timeout_seconds,
                max_retries=self.settings.openai_max_retries,
            )
            ai_provider_type = ProviderType.OPENAI
        else:
            self.ai_provider = FakeAIProvider()
            ai_provider_type = ProviderType.CUSTOM
        self.ai_provider_type = ai_provider_type

        self.memory_service = MemoryService(self.memory_repository)
        self.redaction_policy = RedactionPolicy()
        if self.settings.observability_repository == "postgres":
            self.event_store = PostgresEventStore(self.settings.database_url)
            self.audit_repository = PostgresAuditRepository(self.settings.database_url)
            self.observability_repository = PostgresObservabilityRepository(
                self.settings.database_url
            )
        else:
            self.event_store = InMemoryEventStore(self.redaction_policy)
            self.audit_repository = InMemoryAuditRepository()
            self.observability_repository = InMemoryObservabilityRepository()
        self.audit_projector = AuditProjector(self.audit_repository)
        self.metric_projector = MetricProjector(self.observability_repository)
        self.trace_projector = TraceProjector(self.observability_repository)
        self.alert_projector = AlertProjector(self.observability_repository)
        self.structured_log_projector = StructuredLogProjector(
            self.observability_repository
        )
        self.event_service = EventService(
            self.event_bus,
            self.event_store,
            projectors=(
                self.audit_projector,
                self.metric_projector,
                self.trace_projector,
                self.alert_projector,
                self.structured_log_projector,
            ),
            redaction_policy=self.redaction_policy,
        )
        use_postgres_outbox = any(
            (
                self.settings.operational_repository == "postgres",
                self.settings.memory_repository == "postgres",
                self.settings.runtime_checkpoint_repository == "postgres",
                self.settings.session_repository == "postgres",
            )
        )
        if use_postgres_outbox:
            self.outbox_repository = PostgresOutboxRepository(
                self.settings.database_url
            )
        else:
            self.outbox_repository = InMemoryOutboxRepository()
        self.outbox_service = OutboxService(
            self.outbox_repository,
            self.event_service,
            max_attempts=self.settings.outbox_max_attempts,
            batch_size=self.settings.outbox_batch_size,
        )
        self.event_replay_service = EventReplayService(
            self.event_store,
            projectors=(
                self.audit_projector,
                self.metric_projector,
                self.trace_projector,
                self.alert_projector,
                self.structured_log_projector,
            ),
        )
        self.session_trace_reconstructor = SessionTraceReconstructor(self.event_store)
        self.observability_service = ObservabilityService(
            event_store=self.event_store,
            audit_repository=self.audit_repository,
            observability_repository=self.observability_repository,
            session_reconstructor=self.session_trace_reconstructor,
        )
        self.knowledge_limits = KnowledgeLimits()
        self.knowledge_repository: KnowledgeGraphRepository
        if self.settings.knowledge_repository == "postgres":
            self.knowledge_repository = PostgresKnowledgeGraphRepository(
                self.settings.database_url
            )
        else:
            self.knowledge_repository = InMemoryKnowledgeGraphRepository()
        self.semantic_search_provider = DeterministicSemanticSearchProvider(
            self.knowledge_repository,
            clock=lambda: datetime.now(UTC),
        )
        self.knowledge_graph_service = KnowledgeGraphService(
            self.knowledge_repository,
            semantic_search_provider=self.semantic_search_provider,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
        )
        self.knowledge_context_expander = KnowledgeContextExpander(
            self.knowledge_graph_service,
            self.knowledge_repository,
        )
        self.graph_integrity_service = GraphIntegrityService(
            self.knowledge_repository,
            knowledge_service=self.knowledge_graph_service,
            clock=lambda: datetime.now(UTC),
        )
        self.knowledge_projector = KnowledgeProjector(
            self.knowledge_graph_service,
            clock=lambda: datetime.now(UTC),
        )
        self.event_service.register_projector(self.knowledge_projector)
        self.security_repository: SecurityRepository
        if self.settings.security_repository == "postgres":
            self.security_repository = PostgresSecurityRepository(
                self.settings.database_url
            )
        else:
            self.security_repository = InMemorySecurityRepository()
        self.security_service = SecurityService(
            self.security_repository,
            token_secret=self.settings.auth_token_secret,
            issuer=self.settings.auth_issuer,
            audience=self.settings.auth_audience,
            token_ttl=self.settings.auth_token_ttl,
            token_key_ring=_jwt_key_ring(self.settings),
            active_key_id=self.settings.auth_active_key_id,
            clock_skew_seconds=self.settings.auth_clock_skew_seconds,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
        )
        if self.security_repository.get_user_by_email("admin@ecos.local") is None:
            self.security_service.create_local_user(
                email="admin@ecos.local",
                display_name="ECOS Local Admin",
                password="change-me-development-only",
                organization_name="ECOS Local Organization",
                roles=(Role.ADMIN,),
            )
        if self.settings.memory_repository == "postgres":
            self.context_provider = ContextEngine(
                self.memory_repository,
                event_service=self.event_service,
                knowledge_graph_service=self.knowledge_graph_service,
                context_expander=self.knowledge_context_expander,
            )
        else:
            self.context_provider = FakeContextProvider(organization.id, objective)
        self.observation_repository: ObservationRepository
        self.learning_repository: LearningRepository
        if (
            self.settings.runtime_checkpoint_repository == "postgres"
            or self.settings.session_repository == "postgres"
        ):
            self.observation_repository = PostgresObservationRepository(
                self.settings.database_url
            )
            self.learning_repository = PostgresLearningRepository(
                self.settings.database_url
            )
        else:
            local_outbox = (
                self.outbox_repository
                if isinstance(self.outbox_repository, InMemoryOutboxRepository)
                else None
            )
            self.observation_repository = InMemoryObservationRepository(local_outbox)
            self.learning_repository = InMemoryLearningRepository(outbox=local_outbox)
        self.learning_service = LearningService(
            self.memory_service,
            self.event_service,
            repository=self.learning_repository,
            observation_repository=self.observation_repository,
        )
        self.observation_engine = ObservationEngine(
            measurement_provider=InMemoryMeasurementProvider(),
            feedback_provider=InMemoryFeedbackProvider(),
            idempotency_provider=InMemoryObservationIdempotencyProvider(),
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            config=ObservationConfig(),
            repository=self.observation_repository,
        )
        self.session_service = SessionService(self.session_repository)
        self.tenant_memory_service = TenantScopedMemoryService(
            self.memory_service,
            self.security_service,
        )
        self.tenant_session_service = TenantScopedSessionService(
            self.session_service,
            self.security_service,
        )
        self.context_service = ContextService(self.context_provider)
        self.specialist_registry = SpecialistRegistry()
        for specialist in self.specialist_provider.load():
            self.specialist_registry.register(specialist)
        registered_types = {
            specialist.type for specialist in self.specialist_registry.list()
        }
        for specialist_type in SpecialistType:
            if specialist_type in registered_types:
                continue
            self.specialist_registry.register(
                Specialist(
                    name=f"{specialist_type.value.title()} Specialist",
                    type=specialist_type,
                    description=f"{specialist_type.value} specialist.",
                    capabilities=[
                        Capability(
                            name=f"{specialist_type.value} analysis",
                            description="Deterministic specialist capability.",
                        )
                    ],
                )
            )
        self.cognitive_planner = CognitivePlanner(
            specialist_registry=self.specialist_registry,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
        )
        self.planner_service = PlannerService(
            self.planner_provider,
            self.cognitive_planner,
        )
        self.specialist_service = SpecialistService(
            self.specialist_provider,
            self.specialist_registry,
        )
        self.decision_service = DecisionService(self.decision_provider)
        self.provider_registry = ProviderRegistry()
        self.ai_service = AIService(self.provider_registry)
        self.ai_service.register(ai_provider_type, self.ai_provider, default=True)
        registered_provider = self.provider_registry.get(ai_provider_type)
        if registered_provider is None:
            raise ConfigurationError("Configured AI provider was not registered.")
        if self.settings.ai_provider == "openai":
            self.reasoning_provider = AIReasoningEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.debate_provider = AIDebateEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.simulation_provider = AIWarEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.decision_provider = AIDecisionSupportEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
        else:
            self.reasoning_provider = FakeReasoningProvider()
            self.debate_provider = FakeDebateProvider()
            self.simulation_provider = FakeWarEngine()
        self.decision_service = DecisionService(self.decision_provider)
        self.reasoning_service = ReasoningService(self.reasoning_provider)
        self.debate_service = DebateService(self.debate_provider)
        self.simulation_service = SimulationService(self.simulation_provider)
        self.governance_config = GovernanceConfig()
        self.policy_provider = InMemoryPolicyProvider((demo_policy(organization.id),))
        self.approval_policy_provider = DefaultApprovalPolicyProvider(
            self.governance_config
        )
        self.identity_port = SecurityIdentityPort(self.security_repository)
        self.governance_engine = GovernanceEngine(
            policy_provider=self.policy_provider,
            approval_policy_provider=self.approval_policy_provider,
            event_service=self.event_service,
            identity_port=self.identity_port,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            config=self.governance_config,
        )
        self.connector_registry = ConnectorRegistry()
        self.connector_registry.register(default_in_memory_connector())
        self.idempotency_provider = InMemoryIdempotencyProvider()
        self.human_task_provider = InMemoryHumanTaskProvider()
        self.execution_result_repository: ExecutionResultRepository
        if (
            self.settings.runtime_checkpoint_repository == "postgres"
            or self.settings.session_repository == "postgres"
        ):
            self.execution_result_repository = PostgresExecutionResultRepository(
                self.settings.database_url
            )
        else:
            local_outbox = (
                self.outbox_repository
                if isinstance(self.outbox_repository, InMemoryOutboxRepository)
                else None
            )
            self.execution_result_repository = InMemoryExecutionResultRepository(
                local_outbox
            )
        self.execution_engine = ExecutionEngine(
            connector_registry=self.connector_registry,
            idempotency_provider=self.idempotency_provider,
            human_task_provider=self.human_task_provider,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            concurrency_limit=1,
            default_timeout_seconds=30.0,
            result_repository=self.execution_result_repository,
        )
        self.engine_executors = {
            "context": ContextExecutor(self.context_service),
            "reasoning": ReasoningExecutor(self.reasoning_service),
            "specialists": SpecialistsExecutor(self.specialist_service),
            "debate": DebateExecutor(self.debate_service),
            "simulation": SimulationExecutor(self.simulation_service),
            "decision": DecisionExecutor(self.decision_service),
            "decision_support": DecisionExecutor(
                self.decision_service,
                engine_type="decision_support",
            ),
            "memory": LearningExecutor(self.learning_service, engine_type="memory"),
            "learning": LearningExecutor(
                self.learning_service,
                engine_type="learning",
            ),
            "governance": GovernanceExecutor(self.governance_engine),
            "execution": ExecutionExecutor(self.execution_engine),
            "observation": ObservationExecutor(self.observation_engine),
        }
        self.orchestrator = Orchestrator(
            executors=self.engine_executors,
            event_service=self.event_service,
            session_service=self.session_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            config=OrchestrationConfig(mode=OrchestrationMode.SEQUENTIAL),
        )
        self.orchestrator_service = OrchestratorService(
            self.orchestrator_provider,
            self.orchestrator,
        )
        self.runtime_pipeline = CognitivePipeline(
            memory_repository=self.memory_repository,
            session_repository=self.session_repository,
            event_bus=self.event_bus,
            context_provider=self.context_provider,
            ai_provider=self.ai_provider,
            memory_service=self.memory_service,
            learning_service=self.learning_service,
            session_service=self.session_service,
            event_service=self.event_service,
            context_service=self.context_service,
            planner_service=self.planner_service,
            reasoning_service=self.reasoning_service,
            specialist_service=self.specialist_service,
            debate_service=self.debate_service,
            simulation_service=self.simulation_service,
            decision_service=self.decision_service,
            orchestrator_service=self.orchestrator_service,
            ai_service=self.ai_service,
        )
        self.runtime_artifact_codec = RuntimeArtifactCodec()
        self.authenticated_runtime_service = AuthenticatedRuntimeService(
            session_service=self.session_service,
            planner_service=self.planner_service,
            orchestrator_service=self.orchestrator_service,
            governance_engine=self.governance_engine,
            checkpoint_repository=self.runtime_checkpoint_repository,
            artifact_codec=self.runtime_artifact_codec,
            start_claim_heartbeat_interval=self.settings.runtime_start_claim_heartbeat,
            start_claim_heartbeat_shutdown_timeout=(
                self.settings.runtime_start_claim_heartbeat_shutdown_timeout
            ),
            clock=lambda: datetime.now(UTC),
        )
        self.runtime_engine = RuntimeEngine(
            self.runtime_pipeline,
            self.authenticated_runtime_service,
        )
        if self.settings.security_repository == "postgres":
            self.security_controls = PostgresSecurityControlRepository(
                self.settings.database_url
            )
        else:
            self.security_controls = InMemorySecurityControlRepository()
        self.operational_service = OperationalService(
            security_service=self.security_service,
            security_repository=self.security_repository,
            event_service=self.event_service,
            knowledge_graph_service=self.knowledge_graph_service,
            repository=self._operational_repository(),
            session_service=self.session_service,
            authenticated_runtime_service=self.authenticated_runtime_service,
            demo_seed_enabled=self.settings.demo_seed_enabled,
            environment=self.settings.environment,
            outbox_service=self.outbox_service,
            outbox_enabled=self.settings.outbox_enabled,
        )

    def _operational_repository(self) -> OperationalRepository:
        if self.settings.operational_repository == "postgres":
            return PostgresOperationalRepository(self.settings.database_url)
        return InMemoryOperationalRepository()

    def health(self) -> dict[str, Any]:
        """Return container, provider and runtime health information."""
        provider_health = self.ai_service.health(self.ai_provider_type)
        return {
            "container": "ok",
            "providers": {
                self.ai_provider_type.value: provider_health.status
                is ProviderStatus.AVAILABLE,
            },
            "runtime": isinstance(self.runtime_engine, RuntimeEngine),
        }

    def readiness(self) -> dict[str, Any]:
        """Return short readiness component status without exposing credentials."""
        components: dict[str, dict[str, Any]] = {
            "container": {"status": "healthy"},
            "runtime": {
                "status": "healthy"
                if isinstance(self.runtime_engine, RuntimeEngine)
                else "unhealthy"
            },
            "configuration": {"status": self._configuration_status()},
            "outbox": {"status": "healthy", "counts": self.outbox_repository.counts()},
        }
        schema_revision: str | None = None
        if _uses_postgres(self.settings):
            database = _run_async(self._database_readiness())
            components.update(database["components"])
            schema_revision = database.get("schema_revision")
        ready = all(item["status"] == "healthy" for item in components.values())
        return {
            "ready": ready,
            "schema_revision": schema_revision,
            "components": components,
        }

    def _configuration_status(self) -> str:
        if self.settings.production and self.settings.demo_seed_enabled:
            return "unhealthy"
        if self.settings.production and len(self.settings.auth_token_secret) < 32:
            return "unhealthy"
        return "healthy"

    async def _database_readiness(self) -> dict[str, Any]:
        engine = create_database_engine(self.settings.database_url, self.settings)
        required_tables = {
            "alembic_version",
            "security_users",
            "security_auth_sessions",
            "operational_sessions",
            "operational_idempotency_keys",
            "event_records",
            "transactional_outbox",
        }
        components: dict[str, dict[str, Any]] = {}
        schema_revision: str | None = None
        try:
            async with engine.begin() as connection:
                await connection.execute(text("select 1"))
                schema_revision = await connection.scalar(
                    text("select version_num from alembic_version limit 1")
                )
                rows = (
                    await connection.execute(
                        text(
                            "select table_name from information_schema.tables "
                            "where table_schema='public'"
                        )
                    )
                ).scalars()
                present = set(rows)
        except Exception:
            components["database"] = {"status": "unhealthy"}
            await engine.dispose()
            return {"schema_revision": schema_revision, "components": components}
        finally:
            await engine.dispose()
        missing = sorted(required_tables - present)
        components["database"] = {"status": "healthy"}
        components["schema"] = {
            "status": "healthy" if not missing and schema_revision else "unhealthy",
            "revision": schema_revision,
            "missing_tables": missing,
        }
        return {"schema_revision": schema_revision, "components": components}


def _jwt_key_ring(settings: Settings) -> dict[str, str]:
    if not settings.auth_token_key_ring:
        return {settings.auth_active_key_id: settings.auth_token_secret}
    ring: dict[str, str] = {}
    for item in settings.auth_token_key_ring.split(","):
        key_id, separator, secret = item.partition(":")
        if not separator:
            continue
        ring[key_id.strip()] = secret.strip()
    if settings.auth_active_key_id not in ring:
        ring[settings.auth_active_key_id] = settings.auth_token_secret
    return ring


def _uses_postgres(settings: Settings) -> bool:
    return any(
        value == "postgres"
        for value in (
            settings.session_repository,
            settings.memory_repository,
            settings.observability_repository,
            settings.knowledge_repository,
            settings.security_repository,
            settings.operational_repository,
        )
    )


def _run_async[ResultT](coroutine) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()
