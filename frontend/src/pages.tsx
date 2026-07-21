import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "./api";
import { useAuth } from "./auth";
import {
  AccessDeniedState,
  AuthorityNotice,
  EmptyState,
  ErrorState,
  LoadingState,
  Page,
  Panel,
  SessionPipeline,
  Stat,
  Status
} from "./components";
import type {
  Approval,
  CanonicalExecution,
  CanonicalLearning,
  CanonicalObservation,
  CognitiveSession,
  EventRecord,
  KnowledgeResult,
  LearningReview,
  OperationalSession,
  OutboxMessage,
  Overview,
  ReadinessInfo,
  ValidatedMemory
} from "./types";

function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableLoader = useCallback(loader, deps);

  useEffect(() => {
    let active = true;
    setLoading(true);
    stableLoader()
      .then((value) => {
        if (active) {
          setData(value);
          setError(null);
          setForbidden(false);
        }
      })
      .catch((caught) => {
        if (!active) return;
        if (caught instanceof ApiError && caught.status === 403) setForbidden(true);
        setError(caught instanceof Error ? caught.message : "Falha ao carregar");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [stableLoader]);

  return { data, error, forbidden, loading, setData };
}

function can(permission: string, permissions: string[] | undefined) {
  return Boolean(permissions?.includes(permission));
}

export function LoginPage() {
  const { login, auth, error } = useAuth();
  const [email, setEmail] = useState("operator@demo.ecos.local");
  const [password, setPassword] = useState("operator-demo-password");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  if (auth) navigate("/");

  return (
    <main className="login-page">
      <section className="login-panel">
        <h1>ECOS Operacional</h1>
        <p>Sessão institucional com autenticação HttpOnly.</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setBusy(true);
            void login(email, password)
              .then(() => navigate("/"))
              .finally(() => setBusy(false));
          }}
        >
          <label>
            E-mail
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            Senha
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? <ErrorState>{error}</ErrorState> : null}
          <button disabled={busy}>{busy ? "Entrando..." : "Entrar"}</button>
        </form>
        <div className="demo-note">
          Demo local: operador, aprovador, auditor e administrador organizacional.
        </div>
      </section>
    </main>
  );
}

export function OverviewPage() {
  const { data, loading, error } = useLoad<Overview>(() => api.overview(), []);
  if (loading) return <Page title="Visão Cognitiva"><LoadingState /></Page>;
  if (error || !data) return <Page title="Visão Cognitiva"><ErrorState>{error}</ErrorState></Page>;
  const activeSession = data.recent_sessions[0] ?? null;
  return (
    <Page eyebrow="Cognitive Operating System" title="Visão Cognitiva">
      <AuthorityNotice />
      <section className="workspace-grid">
        <div className="workspace-main">
          <Panel title="Estado operacional cognitivo" tone="signal">
            <div className="metric-strip">
              <Stat label="Sessões" value={data.recent_sessions.length} />
              <Stat label="Aprovações pendentes" value={data.pending_approvals} />
              <Stat label="Execuções ativas" value={data.running_executions} />
              <Stat label="Confiança média" value={data.average_recommendation_confidence.toFixed(2)} />
            </div>
            {activeSession ? (
              <div className="active-objective">
                <span>Objetivo ativo</span>
                <Link to={`/sessions/${activeSession.session_id}`}>{activeSession.objective}</Link>
                <SessionPipeline currentStage={activeSession.status} stages={activeSession.stages} />
              </div>
            ) : (
              <EmptyState>Nenhuma sessão cognitiva registrada.</EmptyState>
            )}
          </Panel>
          <Panel title="Sessões recentes">
            <div className="operational-list">
              {data.recent_sessions.length === 0 ? (
                <EmptyState>Nenhuma sessão disponível.</EmptyState>
              ) : null}
              {data.recent_sessions.map((item) => (
                <Link className="operational-row" key={item.session_id} to={`/sessions/${item.session_id}`}>
                  <span>{item.objective}</span>
                  <Status value={item.status} />
                  <time>{new Date(item.updated_at).toLocaleString()}</time>
                </Link>
              ))}
            </div>
          </Panel>
        </div>
        <ContextOverview data={data} />
      </section>
    </Page>
  );
}

function ContextOverview({ data }: { data: Overview }) {
  return (
    <aside className="context-inspector">
      <Panel title="Context Inspector">
        <dl className="inspector-list">
          <div>
            <dt>Organização</dt>
            <dd>{data.organization.name}</dd>
          </div>
          <div>
            <dt>Usuário</dt>
            <dd>{data.user.display_name}</dd>
          </div>
          <div>
            <dt>Papéis</dt>
            <dd>{data.roles.join(", ") || "sem papel"}</dd>
          </div>
          <div>
            <dt>Saúde dos componentes</dt>
            <dd>{data.component_health.length}</dd>
          </div>
        </dl>
        {data.component_health.map((item) => (
          <div className="row compact" key={item.component}>
            <span>{item.component}</span>
            <Status value={item.status} />
          </div>
        ))}
      </Panel>
      <Panel title="Eventos recentes">
        {data.recent_events.slice(0, 6).map((event) => (
          <div className="row compact" key={event.event_id}>
            <span>{event.event_type}</span>
            <code>{event.correlation_id?.slice(0, 8) ?? "sem-corr"}</code>
          </div>
        ))}
      </Panel>
    </aside>
  );
}

export function SessionsPage() {
  const { auth } = useAuth();
  const { data, loading, error, setData } = useLoad<OperationalSession[]>(
    () => api.sessions(),
    []
  );
  const [objective, setObjective] = useState("Validate controlled ECOS execution");
  const [description, setDescription] = useState("Run the deterministic operational cycle.");
  const [createError, setCreateError] = useState<string | null>(null);
  const navigate = useNavigate();
  const mayCreate = can("sessions:write", auth?.principal.permissions);

  async function create() {
    setCreateError(null);
    try {
      const session = await api.createSession(objective, description);
      setData([session, ...(data ?? [])]);
      navigate(`/sessions/${session.session_id}`);
    } catch (caught) {
      setCreateError(caught instanceof Error ? caught.message : "Falha ao criar sessão");
    }
  }

  return (
    <Page
      title="Sessões Cognitivas"
      actions={<button disabled={!mayCreate} onClick={() => void create()}>Criar sessão</button>}
    >
      {!mayCreate ? <AccessDeniedState /> : null}
      <div className="form-row">
        <input
          aria-label="Objetivo da sessão"
          disabled={!mayCreate}
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
        />
        <input
          aria-label="Descrição da sessão"
          disabled={!mayCreate}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      {loading ? <LoadingState /> : null}
      {error ? <ErrorState>{error}</ErrorState> : null}
      {createError ? <ErrorState>{createError}</ErrorState> : null}
      <div className="session-directory">
        {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhuma sessão encontrada.</EmptyState> : null}
        {(data ?? []).map((item) => (
          <button
            className="session-directory-row"
            key={item.session_id}
            onClick={() => navigate(`/sessions/${item.session_id}`)}
          >
            <span>{item.objective}</span>
            <Status value={item.status} />
            <time>{new Date(item.created_at).toLocaleString()}</time>
          </button>
        ))}
      </div>
    </Page>
  );
}

export function SessionDetailPage() {
  const { auth } = useAuth();
  const { id = "" } = useParams();
  const { data, loading, error, setData } = useLoad<OperationalSession>(
    () => api.session(id),
    [id]
  );
  const cognitive = useLoad<CognitiveSession>(() => api.cognitiveSession(id), [id]);
  const [actionError, setActionError] = useState<string | null>(null);
  const mayStart = can("sessions:write", auth?.principal.permissions);

  async function start() {
    setActionError(null);
    try {
      await api.startCognition(id);
      setData(await api.session(id));
      cognitive.setData(await api.cognitiveSession(id));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Falha ao iniciar cognição");
    }
  }

  if (loading) return <Page title="Sessão"><LoadingState /></Page>;
  if (error || !data) return <Page title="Sessão"><ErrorState>{error}</ErrorState></Page>;
  return (
    <Page
      eyebrow="Cognitive Workspace"
      title={data.objective}
      actions={
        data.status === "created" ? (
          <button disabled={!mayStart} onClick={() => void start()}>Iniciar cognição</button>
        ) : null
      }
    >
      <AuthorityNotice />
      {actionError ? <ErrorState>{actionError}</ErrorState> : null}
      <section className="workspace-grid">
        <div className="workspace-main">
          <Panel title="Pipeline cognitivo" tone="signal">
            <SessionPipeline currentStage={data.status} stages={data.stages} />
          </Panel>
          <Panel title="Artefatos cognitivos associados">
            {cognitive.data && Object.keys(cognitive.data.artifacts).length > 0 ? (
              <div className="artifact-stack">
                <Artifact title="Contexto" value={JSON.stringify(cognitive.data.artifacts.context ?? {}, null, 2)} />
                <Artifact title="Reasoning" value={JSON.stringify(cognitive.data.artifacts.reasoning ?? {}, null, 2)} />
                <Artifact title="Planning" value={JSON.stringify(cognitive.data.planning ?? {}, null, 2)} />
                <Artifact title="Governance" value={JSON.stringify(cognitive.data.artifacts.governance ?? {}, null, 2)} />
              </div>
            ) : (
              <EmptyState>Nenhuma recomendação gerada.</EmptyState>
            )}
          </Panel>
          <Panel title="Riscos, hipóteses e alternativas">
            {data.recommendation ? (
              <div className="evidence-grid">
                <EvidenceList title="Riscos" items={data.recommendation.risks} />
                <EvidenceList title="Evidências" items={data.recommendation.evidence} />
                <EvidenceList title="Plano proposto" items={data.recommendation.plan} />
              </div>
            ) : (
              <EmptyState>Aguardando ciclo cognitivo.</EmptyState>
            )}
          </Panel>
          <Panel title="Timeline">
            {data.timeline.map((item) => (
              <div className="timeline-row" key={item.sequence}>
                <span>{item.message}</span>
                <code>{item.event_type}</code>
                <time>{new Date(item.occurred_at).toLocaleString()}</time>
              </div>
            ))}
          </Panel>
        </div>
        <SessionInspector session={data} />
      </section>
    </Page>
  );
}

function Artifact({ title, value }: { title: string; value: string | null }) {
  return (
    <section className="artifact">
      <h3>{title}</h3>
      <p>{value || "Indisponível no estágio atual."}</p>
    </section>
  );
}

function EvidenceList({ items, title }: { title: string; items: string[] }) {
  return (
    <section>
      <h3>{title}</h3>
      {items.length === 0 ? <p className="muted">Sem itens registrados.</p> : null}
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}

function SessionInspector({ session }: { session: OperationalSession }) {
  const confidence = session.recommendation?.confidence ?? null;
  return (
    <aside className="context-inspector">
      <Panel title="Context Inspector">
        <dl className="inspector-list">
          <div>
            <dt>Estado da sessão</dt>
            <dd><Status value={session.status} /></dd>
          </div>
          <div>
            <dt>Correlação</dt>
            <dd><code>{session.correlation_id.slice(0, 8)}</code></dd>
          </div>
          <div>
            <dt>Confiança</dt>
            <dd>{confidence === null ? "indisponível" : confidence.toFixed(2)}</dd>
          </div>
          <div>
            <dt>Aprovação humana</dt>
            <dd>{session.approval ? <Status value={session.approval.status} /> : "não solicitada"}</dd>
          </div>
          <div>
            <dt>Execução</dt>
            <dd>{session.execution ? <Status value={session.execution.status} /> : "bloqueada sem aprovação"}</dd>
          </div>
        </dl>
      </Panel>
      <Panel title="Contexto organizacional">
        <pre>{JSON.stringify(session.context, null, 2)}</pre>
      </Panel>
      <Panel title="Lacunas e políticas">
        <p>{confidence !== null && confidence < 0.65 ? "Baixa confiança: revisão humana recomendada." : "Sem lacuna crítica registrada pela API."}</p>
        <p>Execução permanece condicionada à aprovação e permissões existentes.</p>
      </Panel>
    </aside>
  );
}

export function ApprovalsPage() {
  const { auth } = useAuth();
  const { data, loading, error, setData } = useLoad<Approval[]>(() => api.approvals(), []);
  const [message, setMessage] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [deciding, setDeciding] = useState<string | null>(null);
  const mayApprove = can("decisions:approve", auth?.principal.permissions);

  const refreshApprovals = useCallback(async () => {
    const refreshed = await api.approvals();
    setData(refreshed);
  }, [setData]);

  useEffect(() => {
    if (!data?.some((item) => item.runtime_status === "executing")) return;
    const timer = window.setInterval(() => {
      void refreshApprovals().catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [data, refreshApprovals]);

  async function decide(item: Approval, approve: boolean) {
    const reason = reasons[item.approval_id]?.trim() ?? "";
    setMessage(null);
    if (!reason) {
      setMessage(`Informe uma justificativa para ${approve ? "aprovar" : "rejeitar"}.`);
      return;
    }
    setDeciding(item.approval_id);
    try {
      const updated = approve
        ? await api.approve(item.approval_id, reason)
        : await api.reject(item.approval_id, reason);
      setData((current) =>
        (current ?? []).map((value) =>
          value.approval_id === item.approval_id ? updated : value
        )
      );
      setReasons((current) => ({ ...current, [item.approval_id]: "" }));
      await refreshApprovals();
    } catch (caught) {
      setMessage(approvalDecisionError(caught));
      try {
        await refreshApprovals();
      } catch {
        // Keep the confirmed card state when the refresh also fails.
      }
    } finally {
      setDeciding(null);
    }
  }

  return (
    <Page title="Aprovações">
      <AuthorityNotice />
      {!mayApprove ? <AccessDeniedState /> : null}
      {message ? <ErrorState>{message}</ErrorState> : null}
      {loading ? <LoadingState /> : null}
      {error ? <ErrorState>{error}</ErrorState> : null}
      <div className="approval-board">
        {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhuma aprovação pendente.</EmptyState> : null}
        {(data ?? []).map((item) => {
          const expired = Boolean(item.expires_at && Date.parse(item.expires_at) <= Date.now());
          const terminal = item.status === "approved" || item.status === "rejected";
          const alreadyDecided = item.decided_by === auth?.principal.user_id;
          const roleAllowed =
            item.runtime_status === null ||
            (item.required_roles.length > 0 &&
              item.required_roles.some((role) => auth?.principal.roles.includes(role)));
          const disabled =
            !mayApprove || !roleAllowed || deciding !== null || terminal || expired || alreadyDecided;
          const remaining = Math.max(item.minimum_approvals - item.approvals_recorded, 0);
          return (
            <div key={item.approval_id} data-session-id={item.session_id}>
            <Panel title={item.requester_email}>
              <Status value={item.status} />
              {item.runtime_status ? (
                <p>Estado atual do runtime: <Status value={item.runtime_status} /></p>
              ) : null}
              <dl className="detail-list">
                {item.action_scope ? <><dt>Ação ou escopo</dt><dd>{item.action_scope}</dd></> : null}
                <dt>Solicitante</dt><dd>{item.requester_email}</dd>
                <dt>Criação</dt><dd>{formatApprovalDate(item.created_at)}</dd>
                {item.expires_at ? <><dt>Expiração</dt><dd>{formatApprovalDate(item.expires_at)}</dd></> : null}
                {item.required_roles.length > 0 ? <><dt>Papéis exigidos</dt><dd>{item.required_roles.join(", ")}</dd></> : null}
                <dt>Quorum mínimo</dt><dd>{item.minimum_approvals}</dd>
                <dt>Aprovações registradas</dt><dd>{item.approvals_recorded}</dd>
              </dl>
              <p><strong>{item.approvals_recorded} de {item.minimum_approvals} aprovações</strong></p>
              {item.status === "partially_approved" ? (
                <p>{remaining} {remaining === 1 ? "decisão ainda aguarda" : "decisões ainda aguardam"} quorum.</p>
              ) : null}
              {expired ? <ErrorState>Esta solicitação de aprovação expirou.</ErrorState> : null}
              {alreadyDecided && !terminal ? <p>Você já registrou uma decisão neste request.</p> : null}
              {item.error_code === "RUNTIME_REJECTED" ? (
                <ErrorState>Runtime rejeitado pela decisão humana (RUNTIME_REJECTED).</ErrorState>
              ) : null}
              <p>Correlation ID: <code>{item.correlation_id}</code></p>
              <EvidenceList title="Plano aguardando decisão" items={item.plan} />
              <EvidenceList title="Riscos declarados" items={item.risks} />
              <label>
                Justificativa
                <textarea
                  value={reasons[item.approval_id] ?? ""}
                  disabled={disabled}
                  maxLength={1000}
                  onChange={(event) =>
                    setReasons((current) => ({
                      ...current,
                      [item.approval_id]: event.target.value
                    }))
                  }
                />
              </label>
              <div className="actions">
                <button disabled={disabled} onClick={() => void decide(item, true)}>
                  {deciding === item.approval_id ? "Registrando..." : "Aprovar"}
                </button>
                <button
                  disabled={disabled}
                  className="secondary"
                  onClick={() => void decide(item, false)}
                >
                  {deciding === item.approval_id ? "Registrando..." : "Rejeitar"}
                </button>
              </div>
            </Panel>
            </div>
          );
        })}
      </div>
    </Page>
  );
}

function formatApprovalDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR");
}

function approvalDecisionError(caught: unknown): string {
  if (!(caught instanceof ApiError)) {
    return caught instanceof Error
      ? `Falha de rede ao registrar decisão: ${caught.message}`
      : "Falha de rede ao registrar decisão.";
  }
  if (caught.status === 403) return "Você não tem permissão para registrar esta decisão.";
  if (caught.status === 409) return "Conflito: a decisão não foi registrada. Atualize o estado e tente novamente.";
  if (caught.status === 410) return "Esta solicitação de aprovação expirou.";
  if (caught.status === 422) return "A justificativa ou os dados da decisão são inválidos.";
  return caught.message || "Decisão recusada.";
}

export function ExecutionsPage() {
  const { data, loading, error } = useLoad<CanonicalExecution[]>(() => api.executions(), []);
  return (
    <Page title="Execuções">
      <AuthorityNotice />
      {loading ? <LoadingState /> : null}
      {error ? <ErrorState>{error}</ErrorState> : null}
      {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhuma execução disponível.</EmptyState> : null}
      {(data ?? []).map((item) => (
        <div key={item.execution_id} data-session-id={item.session_id}>
        <Panel title={`ExecutionResult ${item.execution_id.slice(0, 8)}`}>
          <div className="execution-head">
            <Status value={item.status} />
            <span>{item.mode}</span>
            <code>{item.fingerprint.slice(0, 12)}</code>
          </div>
          <p>Duração: {item.duration.toFixed(3)}s · etapas: {item.step_results.length}</p>
          <pre>{JSON.stringify(item.outputs_by_connector, null, 2)}</pre>
          {item.failures.length ? <pre>{JSON.stringify(item.failures, null, 2)}</pre> : null}
        </Panel>
        </div>
      ))}
    </Page>
  );
}

export function ObservationsPage() {
  const { data, loading, error } = useLoad<CanonicalObservation[]>(() => api.observations(), []);
  return <Page title="Observações">
    {loading ? <LoadingState /> : null}{error ? <ErrorState>{error}</ErrorState> : null}
    {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhum ObservationResult canônico.</EmptyState> : null}
    {(data ?? []).map((item) => <div key={item.observation_id} data-session-id={item.session_id}><Panel title={`ObservationResult ${item.observation_id.slice(0, 8)}`}>
      <Status value={item.status} /><p>Resultado {item.outcome_score.toFixed(2)} · confiança {item.confidence.toFixed(2)}</p>
      <pre>{JSON.stringify({ outcomes: item.observed_outcomes, comparisons: item.comparisons, evidence: item.evidence, quality: item.quality }, null, 2)}</pre>
    </Panel></div>)}
  </Page>;
}

export function KnowledgePage() {
  const [query, setQuery] = useState("execution approval");
  const [results, setResults] = useState<KnowledgeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function search() {
    setLoading(true);
    try {
      setResults(await api.knowledge(query));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha na pesquisa");
    } finally {
      setLoading(false);
    }
  }
  return (
    <Page title="Knowledge Graph" actions={<button onClick={() => void search()}>Pesquisar</button>}>
      <div className="form-row">
        <input aria-label="Consulta no Knowledge Graph" value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      {loading ? <LoadingState label="Pesquisando entidades..." /> : null}
      {error ? <ErrorState>{error}</ErrorState> : null}
      <div className="knowledge-results">
        {results.length === 0 && !loading ? <EmptyState>Nenhuma entidade carregada.</EmptyState> : null}
        {results.map((item) => (
          <div className="knowledge-row" key={item.entity_id}>
            <span>{item.name}</span>
            <span>{item.type}</span>
            <span>confiança {item.confidence.toFixed(2)}</span>
            <span>importância {item.importance.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </Page>
  );
}

export function AuditPage() {
  const { data, loading, error, forbidden } = useLoad<EventRecord[]>(() => api.events(), []);
  return (
    <Page title="Observabilidade">
      {forbidden ? <AccessDeniedState /> : null}
      {loading ? <LoadingState /> : null}
      {error && !forbidden ? <ErrorState>{error}</ErrorState> : null}
      <div className="event-table">
        {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhum evento disponível.</EmptyState> : null}
        {(data ?? []).map((item) => (
          <div className="event-row" key={item.event_id}>
            <span>{item.event_type}</span>
            <span>{item.source}</span>
            <span>{item.category}</span>
            <code>{item.correlation_id?.slice(0, 8) ?? "sem-corr"}</code>
          </div>
        ))}
      </div>
    </Page>
  );
}

export function MemoryPage() {
  const { data, loading, error } = useLoad<ValidatedMemory[]>(() => api.memories(), []);
  return (
    <Page title="Memória">
      {loading ? <LoadingState /> : null}{error ? <ErrorState>{error}</ErrorState> : null}
      {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhuma memória validada.</EmptyState> : null}
      {(data ?? []).map((item) => <div key={item.id} data-session-id={item.session_id}><Panel title={item.title}>
        <Status value={item.validation_status} /><p>{item.description}</p>
        <dl className="detail-list"><dt>Learning</dt><dd><code>{item.learning_id}</code></dd><dt>Candidato</dt><dd><code>{item.learning_candidate_id}</code></dd><dt>Proposta</dt><dd><code>{item.proposal_id}</code></dd><dt>Política</dt><dd>{item.policy_version}</dd><dt>Versão</dt><dd>{item.version}</dd></dl>
        <EvidenceList title="Evidências" items={item.evidence_references ?? []} />
        <EvidenceList title="Provenance" items={item.source_references ?? []} />
      </Panel></div>)}
    </Page>
  );
}

export function GovernancePage() {
  return (
    <Page title="Governança">
      <AuthorityNotice />
      <Panel title="Soberania humana">
        <p>A interface não aprova nem executa decisões autonomamente. Ações sensíveis continuam condicionadas às permissões e aos endpoints de aprovação existentes.</p>
      </Panel>
    </Page>
  );
}

export function LearningPage() {
  const { auth } = useAuth();
  const { data, loading, error, setData } = useLoad<CanonicalLearning[]>(() => api.learning(), []);
  const reviews = useLoad<LearningReview[]>(() => api.learningReviews(), []);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const mayReview = can("decisions:approve", auth?.principal.permissions);
  async function decide(candidateId: string, approve: boolean) {
    const justification = reasons[candidateId]?.trim() ?? "";
    if (!justification) { setMessage("Informe uma justificativa para a revisão."); return; }
    try {
      const updated = await api.decideLearningReview(candidateId, approve, justification);
      setData((data ?? []).map((item) => item.learning_id === updated.learning.learning_id ? updated.learning : item));
      reviews.setData(await api.learningReviews());
      setMessage(null);
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : "Falha na revisão"); }
  }
  return (
    <Page title="Aprendizado">
      {loading ? <LoadingState /> : null}
      {error ? <ErrorState>{error}</ErrorState> : null}
      {message ? <ErrorState>{message}</ErrorState> : null}
      {(data ?? []).length === 0 && !loading ? <EmptyState>Nenhum LearningResult canônico.</EmptyState> : null}
      {(data ?? []).map((item) => (
        <div key={item.learning_id} data-session-id={item.session_id}>
        <Panel title={`LearningResult ${item.learning_id.slice(0, 8)}`}>
          <Status value={item.status} /><pre>{JSON.stringify(item.validation_summary, null, 2)}</pre>
          {item.candidates.map((candidate) => {
            const review = (reviews.data ?? []).find((value) => value.learning_candidate_id === candidate.learning_candidate_id);
            return <section className="artifact" key={candidate.learning_candidate_id}><h3>{candidate.category}</h3><Status value={review?.status ?? candidate.validation_status} /><pre>{JSON.stringify(candidate.statement, null, 2)}</pre>
              {review?.status === "pending" ? <><textarea aria-label={`Justificativa ${candidate.learning_candidate_id}`} value={reasons[candidate.learning_candidate_id] ?? ""} onChange={(event) => setReasons((current) => ({...current, [candidate.learning_candidate_id]: event.target.value}))} /><div className="actions"><button disabled={!mayReview} onClick={() => void decide(candidate.learning_candidate_id, true)}>Aprovar candidato</button><button className="secondary" disabled={!mayReview} onClick={() => void decide(candidate.learning_candidate_id, false)}>Rejeitar candidato</button></div></> : null}
              {review?.justification ? <p>Justificativa: {review.justification} · ator {review.actor_id} · versão {review.version}</p> : null}
            </section>;
          })}
        </Panel>
        </div>
      ))}
    </Page>
  );
}

export function AdminPage() {
  const { auth } = useAuth();
  const { data, loading, error, forbidden } = useLoad<Array<Record<string, unknown>>>(
    () => api.members(),
    []
  );
  const readiness = useLoad<ReadinessInfo>(() => api.readiness(), []);
  const outbox = useLoad<OutboxMessage[]>(() => api.outbox(), []);
  const [reconcileResult, setReconcileResult] = useState<string | null>(null);
  const [reconcileError, setReconcileError] = useState<string | null>(null);
  const mayAdmin = can("organization:admin", auth?.principal.permissions);
  async function reconcile() {
    setReconcileError(null);
    try {
      const result = await api.reconcile();
      setReconcileResult(JSON.stringify(result));
    } catch (caught) {
      setReconcileError(caught instanceof Error ? caught.message : "Reconciliação recusada");
    }
  }
  return (
    <Page
      title="Administração Organizacional"
      actions={<button disabled={!mayAdmin} onClick={() => void reconcile()}>Reconciliar</button>}
    >
      {!mayAdmin || forbidden ? <AccessDeniedState /> : null}
      {reconcileResult ? <div className="notice">{reconcileResult}</div> : null}
      {reconcileError ? <ErrorState>{reconcileError}</ErrorState> : null}
      {loading ? <LoadingState /> : null}
      {error && !forbidden ? <ErrorState>{error}</ErrorState> : null}
      <div className="workspace-grid">
        <div className="workspace-main">
          {(data ?? []).map((item, index) => (
            <Panel key={index} title={(item.user as { email?: string })?.email ?? "Membro"}>
              <pre>{JSON.stringify(item, null, 2)}</pre>
            </Panel>
          ))}
        </div>
        <aside className="context-inspector">
          <Panel title="Readiness">
            {readiness.error ? <ErrorState>{readiness.error}</ErrorState> : null}
            {readiness.data ? (
              <>
                <Status value={readiness.data.ready ? "healthy" : "unhealthy"} />
                <p>Schema: <code>{readiness.data.schema_revision ?? "indisponível"}</code></p>
                {Object.entries(readiness.data.components).map(([name, component]) => (
                  <div className="row compact" key={name}>
                    <span>{name}</span>
                    <Status value={String(component.status)} />
                  </div>
                ))}
              </>
            ) : null}
          </Panel>
          <Panel title="Outbox">
            {outbox.error ? <ErrorState>{outbox.error}</ErrorState> : null}
            {(outbox.data ?? []).slice(0, 8).map((item) => (
              <div className="row compact" key={item.message_id}>
                <span>{item.event_type}</span>
                <Status value={item.status} />
              </div>
            ))}
          </Panel>
        </aside>
      </div>
    </Page>
  );
}
