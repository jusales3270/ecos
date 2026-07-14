import type { NavigateFunction } from "react-router-dom";
import type { SaraAction } from "./saraTypes";

export function isSaraAction(value: unknown): value is SaraAction {
  if (!value || typeof value !== "object" || typeof (value as { type?: unknown }).type !== "string") return false;
  const action = value as Record<string, unknown>;
  if (["open_approvals", "open_executions", "minimize_panel", "close_panel"].includes(String(action.type))) return true;
  if (action.type === "open_session") return typeof action.session_id === "string" && /^[0-9a-f-]{36}$/i.test(action.session_id);
  return false;
}
export function runSaraAction(action: SaraAction, navigate: NavigateFunction, minimize: () => void): void {
  const fixed: Partial<Record<SaraAction["type"], string>> = { open_approvals: "/approvals", open_executions: "/executions" };
  if (action.type === "minimize_panel") return minimize();
  if (action.type === "close_panel") return;
  const route = action.type === "open_session" ? `/sessions/${action.session_id}` : fixed[action.type];
  if (route) { minimize(); navigate(route); }
}
