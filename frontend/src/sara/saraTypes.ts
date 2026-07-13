export type SaraMode = "closed" | "full" | "mini";
export type SaraState = "idle" | "listening" | "thinking" | "speaking" | "offline" | "error" | "waiting_approval" | "executing";
export type SaraPoint = { x: number; y: number };
export type SaraHistoryItem = { role: "user" | "assistant"; content: string };
export type SaraAction =
  | { type: "open_session"; session_id: string }
  | { type: "open_approvals" | "open_executions" | "open_memory" | "open_knowledge" | "open_governance" | "open_observability" | "close_panels" | "minimize_sara" }
  | { type: "navigate"; route: string };
export type SaraResponse = {
  response: string; session_id: string; cognitive_state: string; ui_actions: SaraAction[];
  unavailable: boolean; incomplete_context: boolean;
};
export type SaraPreferences = { mode: SaraMode; position: SaraPoint; voice: boolean; expansionAllowed: boolean };
