import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  Brain,
  CheckSquare,
  CircleGauge,
  Database,
  FileClock,
  LogOut,
  Network,
  Shield,
  Users
} from "lucide-react";
import { useAuth } from "./auth";

const nav = [
  { to: "/", label: "Visão Geral", icon: CircleGauge },
  { to: "/sessions", label: "Sessões", icon: Brain },
  { to: "/approvals", label: "Aprovações", icon: CheckSquare },
  { to: "/executions", label: "Execuções", icon: Activity },
  { to: "/knowledge", label: "Knowledge Graph", icon: Network },
  { to: "/audit", label: "Auditoria", icon: FileClock },
  { to: "/admin", label: "Admin", icon: Users }
];

export function AppShell() {
  const { auth, logout } = useAuth();
  return (
    <div className="app-shell">
      {auth?.demo ? <div className="demo-banner">Ambiente demo local</div> : null}
      <aside className="sidebar">
        <div className="brand">
          <Shield aria-hidden="true" />
          <span>ECOS</span>
        </div>
        <nav aria-label="Navegação principal">
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              <item.icon aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <button className="ghost icon-text" onClick={() => void logout()}>
          <LogOut aria-hidden="true" />
          <span>Sair</span>
        </button>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <strong>{auth?.organization.name}</strong>
            <span>{auth?.principal.roles.join(", ")}</span>
          </div>
          <div>{auth?.principal.user_id.slice(0, 8)}</div>
        </header>
        <Outlet />
      </div>
    </div>
  );
}

export function Page({
  title,
  actions,
  children
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="page">
      <div className="page-heading">
        <h1>{title}</h1>
        {actions}
      </div>
      {children}
    </main>
  );
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value
}: {
  label: string;
  value: string | number;
}) {
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
  return <div className="empty"><Database aria-hidden="true" />{children}</div>;
}
