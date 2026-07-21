import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Brain,
  CheckSquare,
  ChevronDown,
  ChevronUp,
  CircleGauge,
  Command,
  Database,
  FileClock,
  GitBranch,
  GraduationCap,
  Layers,
  LogOut,
  Network,
  PlayCircle,
  Search,
  Shield,
  Sparkles,
  Users,
  type LucideIcon
} from "lucide-react";
import { api } from "./api";
import { useAuth } from "./auth";
import { SaraPresenceLayer } from "./sara/SaraPresenceLayer";
import type { EventRecord, Overview, VersionInfo } from "./types";

type NavItem = {
  to: string;
  label: string;
  area: string;
  icon: LucideIcon;
  permission?: string;
};

const navItems: NavItem[] = [
  { to: "/", label: "Visão Cognitiva", area: "Core", icon: CircleGauge },
  { to: "/sessions", label: "Sessões", area: "Ciclo", icon: Brain },
  { to: "/memory", label: "Memória", area: "Contexto", icon: Database, permission: "memory:read" },
  {
    to: "/knowledge",
    label: "Knowledge Graph",
    area: "Contexto",
    icon: Network,
    permission: "knowledge_graph:read"
  },
  { to: "/governance", label: "Governança", area: "Controle", icon: Shield },
  {
    to: "/approvals",
    label: "Aprovações",
    area: "Controle",
    icon: CheckSquare,
    permission: "decisions:approve"
  },
  {
    to: "/executions",
    label: "Execuções",
    area: "Operação",
    icon: PlayCircle,
    permission: "execution:execute"
  },
  {
    to: "/observations",
    label: "Observações",
    area: "Operação",
    icon: Activity,
    permission: "observation:read"
  },
  {
    to: "/audit",
    label: "Observabilidade",
    area: "Operação",
    icon: FileClock,
    permission: "events:read"
  },
  {
    to: "/learning",
    label: "Aprendizado",
    area: "Evolução",
    icon: GraduationCap,
    permission: "learning:read"
  },
  {
    to: "/admin",
    label: "Administração",
    area: "Controle",
    icon: Users,
    permission: "organization:admin"
  }
];

const commandSearch = [
  ...navItems.map((item) => ({
    id: `nav:${item.to}`,
    label: item.label,
    detail: item.area,
    to: item.to,
    permission: item.permission
  })),
  {
    id: "open:approvals",
    label: "Abrir aprovações pendentes",
    detail: "Governança humana",
    to: "/approvals",
    permission: "decisions:approve"
  },
  {
    id: "open:executions",
    label: "Acessar execuções aprovadas",
    detail: "Execução exige aprovação",
    to: "/executions",
    permission: "execution:execute"
  }
];

function hasPermission(permissions: string[] | undefined, permission: string | undefined) {
  return !permission || Boolean(permissions?.includes(permission));
}

export function CognitiveOsShell() {
  const { auth, logout } = useAuth();
  const permissions = auth?.principal.permissions ?? [];
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.allSettled([api.version(), api.overview(), api.events()]).then((results) => {
      if (!active) return;
      const [versionResult, overviewResult, eventsResult] = results;
      if (versionResult.status === "fulfilled") setVersion(versionResult.value);
      if (overviewResult.status === "fulfilled") setOverview(overviewResult.value);
      if (eventsResult.status === "fulfilled") setEvents(eventsResult.value);
      const failed = results.find((item) => item.status === "rejected");
      setSystemError(failed ? "Dados operacionais parciais" : null);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="cognitive-os">
      <SaraPresenceMount />
      <SystemTopBar
        environment={version?.environment ?? (auth?.demo ? "demo" : "indisponível")}
        globalState={overview ? deriveGlobalState(overview) : "sincronizando"}
        health={deriveHealth(overview, systemError)}
        onOpenCommand={() => setPaletteOpen(true)}
        organization={auth?.organization.name ?? "Organização indisponível"}
        user={overview?.user.display_name ?? auth?.principal.user_id.slice(0, 8) ?? "Usuário"}
        version={version?.version ?? "indisponível"}
      />
      <div className="cognitive-body">
        <CognitiveRail
          items={navItems.filter((item) =>
            item.to === "/admin" ? hasPermission(permissions, item.permission) : true
          )}
          onLogout={() => void logout()}
        />
        <section className="cognitive-surface" aria-label="Área de trabalho cognitiva">
          <Outlet />
        </section>
      </div>
      <EventConsole events={events} error={systemError} />
      <CommandPalette
        commands={commandSearch.filter((item) =>
          item.to === "/admin" ? hasPermission(permissions, item.permission) : true
        )}
        onClose={() => setPaletteOpen(false)}
        open={paletteOpen}
      />
    </div>
  );
}

export function AppShell() {
  return <CognitiveOsShell />;
}

export function SaraPresenceMount() {
  return <div id="sara-presence-mount"><SaraPresenceLayer /></div>;
}

function SystemTopBar({
  environment,
  globalState,
  health,
  onOpenCommand,
  organization,
  user,
  version
}: {
  environment: string;
  globalState: string;
  health: string;
  onOpenCommand: () => void;
  organization: string;
  user: string;
  version: string;
}) {
  return (
    <header className="system-topbar">
      <div className="system-identity">
        <Shield aria-hidden="true" />
        <div>
          <strong>E.C.O.S.</strong>
          <span>{organization}</span>
        </div>
      </div>
      <div className="system-signals" aria-label="Estado do sistema">
        <Signal label="Ambiente" value={environment} />
        <Signal label="Versão" value={version} />
        <Signal label="Saúde" value={health} tone={health === "operacional" ? "good" : "warn"} />
        <Signal label="Estado" value={globalState} />
        <Signal label="Usuário" value={user} />
      </div>
      <button className="command-trigger" onClick={onOpenCommand}>
        <Search aria-hidden="true" />
        <span>Buscar comando</span>
        <kbd>Ctrl K</kbd>
      </button>
    </header>
  );
}

function Signal({
  label,
  tone,
  value
}: {
  label: string;
  tone?: "good" | "warn";
  value: string;
}) {
  return (
    <div className={`signal ${tone ? `signal-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CognitiveRail({ items, onLogout }: { items: NavItem[]; onLogout: () => void }) {
  return (
    <aside className="cognitive-rail">
      <nav aria-label="Navegação cognitiva">
        {items.map((item) => (
          <NavLink aria-label={item.label} key={item.to} to={item.to} end={item.to === "/"}>
            <item.icon aria-hidden="true" />
            <span>{item.label}</span>
            <small>{item.area}</small>
          </NavLink>
        ))}
      </nav>
      <button className="rail-logout" onClick={onLogout}>
        <LogOut aria-hidden="true" />
        <span>Sair</span>
      </button>
    </aside>
  );
}

function EventConsole({ error, events }: { error: string | null; events: EventRecord[] }) {
  const [expanded, setExpanded] = useState(false);
  const visibleEvents = expanded ? events.slice(0, 12) : events.slice(0, 4);
  return (
    <aside className={`event-console ${expanded ? "expanded" : ""}`} aria-label="Console de eventos">
      <button className="event-console-toggle" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronDown aria-hidden="true" /> : <ChevronUp aria-hidden="true" />}
        <span>Event Console</span>
        <strong>{events.length}</strong>
      </button>
      <div className="event-stream">
        {error ? (
          <div className="console-alert">
            <AlertTriangle aria-hidden="true" />
            {error}
          </div>
        ) : null}
        {visibleEvents.length === 0 && !error ? (
          <span className="muted">Nenhum evento recebido.</span>
        ) : null}
        {visibleEvents.map((event) => (
          <div className="console-event" key={event.event_id}>
            <span>{event.event_type}</span>
            <code>{event.correlation_id?.slice(0, 8) ?? "sem-corr"}</code>
            <time>{new Date(event.occurred_at).toLocaleTimeString()}</time>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function CommandPalette({
  commands,
  onClose,
  open
}: {
  commands: Array<{ id: string; label: string; detail: string; to: string }>;
  onClose: () => void;
  open: boolean;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () =>
      commands.filter((item) =>
        `${item.label} ${item.detail}`.toLowerCase().includes(query.toLowerCase())
      ),
    [commands, query]
  );

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  if (!open) return null;
  return (
    <div className="palette-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-label="Command Palette"
        aria-modal="true"
        className="command-palette"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="palette-input">
          <Command aria-hidden="true" />
          <input
            autoFocus
            aria-label="Buscar comando"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onClose();
              if (event.key === "Enter" && filtered[0]) {
                navigate(filtered[0].to);
                onClose();
              }
            }}
            placeholder="Navegar, localizar sessões, abrir aprovações..."
            value={query}
          />
        </div>
        <div className="palette-results">
          {filtered.length === 0 ? <EmptyState>Nenhuma área encontrada.</EmptyState> : null}
          {filtered.map((item) => (
            <button
              className="palette-result"
              key={item.id}
              onClick={() => {
                navigate(item.to);
                onClose();
              }}
            >
              <span>{item.label}</span>
              <small>{item.detail}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

export function Page({
  actions,
  children,
  eyebrow,
  title
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="page">
      <div className="page-heading">
        <div>
          {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
          <h1>{title}</h1>
        </div>
        {actions}
      </div>
      {children}
    </main>
  );
}

export function Panel({
  children,
  title,
  tone = "default"
}: {
  title: string;
  children: ReactNode;
  tone?: "default" | "critical" | "signal";
}) {
  return (
    <section className={`panel panel-${tone}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}>{value}</span>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Layers aria-hidden="true" />
      {children}
    </div>
  );
}

export function LoadingState({ label = "Carregando dados operacionais..." }: { label?: string }) {
  return (
    <div className="state-block">
      <Activity aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ children }: { children: ReactNode }) {
  return (
    <div className="error">
      <AlertTriangle aria-hidden="true" />
      {children}
    </div>
  );
}

export function AccessDeniedState() {
  return <ErrorState>Acesso negado pela política da organização.</ErrorState>;
}

export function AuthorityNotice() {
  return (
    <div className="authority-notice">
      <Sparkles aria-hidden="true" />
      <span>Recomendação não é decisão. Execução exige aprovação humana explícita.</span>
    </div>
  );
}

export function SessionPipeline({
  currentStage,
  stages
}: {
  currentStage: string;
  stages: string[];
}) {
  const lifecycle = [
    { label: "Contexto", keys: ["contexto", "context"] },
    { label: "Raciocínio", keys: ["raciocínio", "raciocinio", "reasoning"] },
    { label: "Debate", keys: ["debate"] },
    { label: "Simulação", keys: ["simulação", "simulacao", "simulation"] },
    { label: "Recomendação", keys: ["recomendação", "recomendacao", "recommendation"] },
    { label: "Aprovação", keys: ["aprovação", "aprovacao", "approval"] },
    { label: "Execução", keys: ["execução", "execucao", "execution"] },
    { label: "Observação", keys: ["observação", "observacao", "observation"] },
    { label: "Aprendizado", keys: ["aprendizado", "learning"] }
  ];
  const normalizedStages = stages.map((item) => item.toLowerCase());
  return (
    <ol className="session-pipeline" aria-label="Pipeline cognitivo">
      {lifecycle.map((stage) => {
        const complete = normalizedStages.some((item) =>
          stage.keys.some((key) => item.includes(key))
        );
        const active = stage.keys.includes(currentStageForStatus(currentStage));
        return (
          <li className={active ? "active" : complete ? "complete" : ""} key={stage.label}>
            <GitBranch aria-hidden="true" />
            <span>{stage.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function deriveHealth(overview: Overview | null, error: string | null) {
  if (error) return "parcial";
  if (!overview) return "sincronizando";
  return overview.component_health.every((item) => item.status === "healthy")
    ? "operacional"
    : "atenção";
}

function deriveGlobalState(overview: Overview) {
  if (overview.running_executions > 0) return "executando";
  if (overview.pending_approvals > 0) return "aguardando aprovação";
  return "observando";
}

function currentStageForStatus(status: string) {
  const map: Record<string, string> = {
    approved: "aprovação",
    completed: "aprendizado",
    created: "contexto",
    executing: "execução",
    failed: "observação",
    processing: "raciocínio",
    rejected: "aprovação",
    waiting_approval: "aprovação",
    waiting_human_review: "aprendizado"
  };
  return map[status] ?? status.toLowerCase();
}
