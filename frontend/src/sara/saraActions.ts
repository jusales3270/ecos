import type { NavigateFunction } from "react-router-dom";
import type { SaraAction } from "./saraTypes";

const routes = new Set(["/", "/sessions", "/approvals", "/executions", "/memory", "/knowledge", "/governance", "/audit", "/learning", "/admin"]);
export function isSaraAction(value: unknown): value is SaraAction {
  if (!value || typeof value !== "object" || typeof (value as { type?: unknown }).type !== "string") return false;
  const action = value as Record<string, unknown>;
  if (["open_approvals", "open_executions", "open_memory", "open_knowledge", "open_governance", "open_observability", "close_panels", "minimize_sara"].includes(String(action.type))) return true;
  if (action.type === "open_session") return typeof action.session_id === "string" && /^[0-9a-f-]{36}$/i.test(action.session_id);
  return action.type === "navigate" && typeof action.route === "string" && routes.has(action.route);
}
export function runSaraAction(action: SaraAction, navigate: NavigateFunction, minimize: () => void): void {
  const fixed: Partial<Record<SaraAction["type"], string>> = { open_approvals: "/approvals", open_executions: "/executions", open_memory: "/memory", open_knowledge: "/knowledge", open_governance: "/governance", open_observability: "/audit" };
  if (action.type === "minimize_sara") return minimize();
  if (action.type === "close_panels") return;
  const route = action.type === "open_session" ? `/sessions/${action.session_id}` : action.type === "navigate" ? action.route : fixed[action.type];
  if (route) { minimize(); navigate(route); }
}
