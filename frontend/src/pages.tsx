import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "./api";
import { useAuth } from "./auth";
import { EmptyState, Page, Panel, Stat, Status } from "./components";
import type {
  Approval,
  EventRecord,
  Execution,
  KnowledgeResult,
  OperationalSession,
  Overview
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
        <p>Autenticação local com sessão HttpOnly.</p>
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
          {error ? <div className="error">{error}</div> : null}
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
  if (loading) return <Page title="Visão Geral"><p>Carregando...</p></Page>;
  if (error || !data) return <Page title="Visão Geral"><div className="error">{error}</div></Page>;
  return (
    <Page title="Visão Geral">
      <div className="stats-grid">
        <Stat label="Sessões" value={data.recent_sessions.length} />
        <Stat label="Aprovações pendentes" value={data.pending_approvals} />
        <Stat label="Execuções ativas" value={data.running_executions} />
        <Stat label="Taxa de aprovação" value={`${Math.round(data.approval_rate * 100)}%`} />
        <Stat label="Sucesso execução" value={`${Math.round(data.execution_success_rate * 100)}%`} />
        <Stat label="Confiança média" value={data.average_recommendation_confidence.toFixed(2)} />
      </div>
      <div className="grid two">
        <Panel title="Sessões recentes">
          {data.recent_sessions.map((item) => (
            <div className="row" key={item.session_id}>
              <span>{item.objective}</span>
              <Status value={item.status} />
            </div>
          ))}
        </Panel>
        <Panel title="Saúde e eventos">
          {data.component_health.map((item) => (
            <div className="row" key={item.component}>
              <span>{item.component}</span>
              <Status value={item.status} />
            </div>
          ))}
          {data.recent_events.slice(0, 5).map((event) => (
            <div className="row compact" key={event.event_id}>
              <span>{event.event_type}</span>
              <code>{event.correlation_id?.slice(0, 8)}</code>
            </div>
          ))}
        </Panel>
      </div>
    </Page>
  );
}

export function SessionsPage() {
  const { data, loading, error, setData } = useLoad<OperationalSession[]>(
    () => api.sessions(),
    []
  );
  const [objective, setObjective] = useState("Validate controlled ECOS execution");
  const [description, setDescription] = useState("Run the deterministic operational cycle.");
  const navigate = useNavigate();

  async function create() {
    const session = await api.createSession(objective, description);
    setData([session, ...(data ?? [])]);
    navigate(`/sessions/${session.session_id}`);
  }

  return (
    <Page
      title="Sessões Cognitivas"
      actions={<button onClick={() => void create()}>Criar sessão</button>}
    >
      <div className="form-row">
        <input value={objective} onChange={(event) => setObjective(event.target.value)} />
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </div>
      {loading ? <p>Carregando...</p> : null}
      {error ? <div className="error">{error}</div> : null}
      <div className="table">
        {(data ?? []).map((item) => (
          <button className="table-row" key={item.session_id} onClick={() => navigate(`/sessions/${item.session_id}`)}>
            <span>{item.objective}</span>
            <Status value={item.status} />
            <span>{new Date(item.created_at).toLocaleString()}</span>
          </button>
        ))}
      </div>
    </Page>
  );
}

export function SessionDetailPage() {
  const { id = "" } = useParams();
  const { data, loading, error, setData } = useLoad<OperationalSession>(
    () => api.session(id),
    [id]
  );

  async function start() {
    setData(await api.startCognition(id));
  }

  if (loading) return <Page title="Sessão"><p>Carregando...</p></Page>;
  if (error || !data) return <Page title="Sessão"><div className="error">{error}</div></Page>;
  return (
    <Page
      title={data.objective}
      actions={
        data.status === "created" ? (
          <button onClick={() => void start()}>Iniciar cognição</button>
        ) : null
      }
    >
      <div className="grid two">
        <Panel title="Contexto">
          <pre>{JSON.stringify(data.context, null, 2)}</pre>
        </Panel>
        <Panel title="Recomendação">
          {data.recommendation ? (
            <>
              <p>{data.recommendation.summary}</p>
              <Stat label="Confiança" value={data.recommendation.confidence} />
              <h3>Riscos</h3>
              <ul>{data.recommendation.risks.map((item) => <li key={item}>{item}</li>)}</ul>
              <h3>Evidências</h3>
              <ul>{data.recommendation.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
            </>
          ) : (
            <EmptyState>Nenhuma recomendação gerada.</EmptyState>
          )}
        </Panel>
      </div>
      <Panel title="Timeline">
        {data.timeline.map((item) => (
          <div className="row" key={item.sequence}>
            <span>{item.message}</span>
            <code>{item.event_type}</code>
          </div>
        ))}
      </Panel>
    </Page>
  );
}

export function ApprovalsPage() {
  const { data, loading, error, setData } = useLoad<Approval[]>(() => api.approvals(), []);
  const [message, setMessage] = useState<string | null>(null);

  async function decide(id: string, approve: boolean) {
    setMessage(null);
    try {
      const updated = approve
        ? await api.approve(id)
        : await api.reject(id, "Rejected from operational UI");
      setData((data ?? []).map((item) => (item.approval_id === id ? updated : item)));
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Decisão recusada");
    }
  }

  return (
    <Page title="Aprovações">
      {message ? <div className="error">{message}</div> : null}
      {loading ? <p>Carregando...</p> : null}
      {error ? <div className="error">{error}</div> : null}
      {(data ?? []).map((item) => (
        <Panel key={item.approval_id} title={item.requester_email}>
          <Status value={item.status} />
          <p>Correlation ID: <code>{item.correlation_id}</code></p>
          <ul>{item.plan.map((step) => <li key={step}>{step}</li>)}</ul>
          <div className="actions">
            <button disabled={item.status !== "pending"} onClick={() => void decide(item.approval_id, true)}>Aprovar</button>
            <button disabled={item.status !== "pending"} className="secondary" onClick={() => void decide(item.approval_id, false)}>Rejeitar</button>
          </div>
        </Panel>
      ))}
    </Page>
  );
}

export function ExecutionsPage() {
  const { data, loading, error, setData } = useLoad<Execution[]>(() => api.executions(), []);
  async function start(id: string) {
    const updated = await api.startExecution(id);
    setData((data ?? []).map((item) => (item.execution_id === id ? updated : item)));
  }
  return (
    <Page title="Execuções">
      {loading ? <p>Carregando...</p> : null}
      {error ? <div className="error">{error}</div> : null}
      {(data ?? []).map((item) => (
        <Panel key={item.execution_id} title={item.connector_id}>
          <Status value={item.status} />
          <p>{item.result ?? item.error ?? "Aguardando aprovação explícita."}</p>
          <ul>{item.approved_plan.map((step) => <li key={step}>{step}</li>)}</ul>
          <button disabled={item.status !== "ready"} onClick={() => void start(item.execution_id)}>
            Iniciar execução
          </button>
          {item.observations.map((obs) => <p key={obs}>{obs}</p>)}
          {item.learning.map((learn) => <p key={learn}>{learn}</p>)}
        </Panel>
      ))}
    </Page>
  );
}

export function KnowledgePage() {
  const [query, setQuery] = useState("execution approval");
  const [results, setResults] = useState<KnowledgeResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  async function search() {
    try {
      setResults(await api.knowledge(query));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Falha na pesquisa");
    }
  }
  return (
    <Page title="Knowledge Graph" actions={<button onClick={() => void search()}>Pesquisar</button>}>
      <input value={query} onChange={(event) => setQuery(event.target.value)} />
      {error ? <div className="error">{error}</div> : null}
      <div className="table">
        {results.map((item) => (
          <div className="table-row" key={item.entity_id}>
            <span>{item.name}</span>
            <span>{item.type}</span>
            <span>{item.confidence.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </Page>
  );
}

export function AuditPage() {
  const { data, loading, error, forbidden } = useLoad<EventRecord[]>(() => api.events(), []);
  return (
    <Page title="Auditoria e Observabilidade">
      {forbidden ? <div className="error">Acesso negado.</div> : null}
      {loading ? <p>Carregando...</p> : null}
      {error && !forbidden ? <div className="error">{error}</div> : null}
      <div className="table">
        {(data ?? []).map((item) => (
          <div className="table-row" key={item.event_id}>
            <span>{item.event_type}</span>
            <span>{item.source}</span>
            <code>{item.correlation_id?.slice(0, 8)}</code>
          </div>
        ))}
      </div>
    </Page>
  );
}

export function AdminPage() {
  const { data, loading, error, forbidden } = useLoad<Array<Record<string, unknown>>>(
    () => api.members(),
    []
  );
  const [reconcileResult, setReconcileResult] = useState<string | null>(null);
  async function reconcile() {
    const result = await api.reconcile();
    setReconcileResult(JSON.stringify(result));
  }
  return (
    <Page title="Administração Organizacional" actions={<button onClick={() => void reconcile()}>Reconciliar</button>}>
      {reconcileResult ? <div className="notice">{reconcileResult}</div> : null}
      {forbidden ? <div className="error">Acesso negado.</div> : null}
      {loading ? <p>Carregando...</p> : null}
      {error && !forbidden ? <div className="error">{error}</div> : null}
      {(data ?? []).map((item, index) => (
        <Panel key={index} title={(item.user as { email?: string })?.email ?? "Membro"}>
          <pre>{JSON.stringify(item, null, 2)}</pre>
        </Panel>
      ))}
    </Page>
  );
}
