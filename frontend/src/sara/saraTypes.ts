export type SaraMode = "closed" | "full" | "mini";
export type SaraState = "idle" | "listening" | "thinking" | "speaking" | "offline" | "error" | "waiting_approval" | "executing";
export type SaraPoint = { x: number; y: number };
export type SaraHistoryItem = { role: "user" | "assistant"; content: string };
export type SaraRuntimeState = "thinking" | "waiting_approval" | "executing" | "completed" | "error";
export type SaraRuntime = {
  state: SaraRuntimeState;
  lifecycle_status: string;
  stage: string | null;
  active_engine: string | null;
  progress: number;
  version: number;
  updated_at: string;
  error_code: string | null;
};
export type SaraAction =
  | { type: "open_session"; session_id: string }
  | { type: "open_approvals" | "open_executions" | "minimize_panel" | "close_panel" };
export type SaraResponse = {
  interaction_id: string; response: string; session_id: string; runtime: SaraRuntime; ui_actions: SaraAction[];
  unavailable: boolean; incomplete_context: boolean;
};
export type SaraSessionState = { session_id: string; runtime: SaraRuntime };
export type SaraStatePollResult = {
  notModified: boolean;
  state: SaraSessionState | null;
  etag: string | null;
  retryAfterMs: number | null;
};
export type SaraPreferences = { mode: SaraMode; position: SaraPoint; voice: boolean; expansionAllowed: boolean };
