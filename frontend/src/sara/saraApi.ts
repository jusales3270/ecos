import { ApiError } from "../api";
import type {
  SaraHistoryItem,
  SaraResponse,
  SaraRuntime,
  SaraSessionState,
  SaraStatePollResult
} from "./saraTypes";

const runtimeStates = new Set(["thinking", "waiting_approval", "executing", "completed", "error"]);

export async function sendSaraInteraction(
  message: string,
  history: SaraHistoryItem[],
  sessionId: string | null,
  route: string,
  signal?: AbortSignal
): Promise<SaraResponse> {
  const response = await fetch("/api/v1/sara/interactions", {
    method: "POST",
    credentials: "include",
    signal,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf(),
      "Idempotency-Key": `sara.interact:${crypto.randomUUID()}`
    },
    body: JSON.stringify({
      message: message.slice(0, 2000),
      history: history.slice(-12),
      session_id: sessionId,
      route_context: route
    })
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw apiError(response);
  if (!validResponse(data)) throw new Error("Resposta inválida do serviço SARA");
  return data;
}

export async function getSaraSessionState(
  sessionId: string,
  etag: string | null,
  signal: AbortSignal
): Promise<SaraStatePollResult> {
  const headers = new Headers();
  if (etag) headers.set("If-None-Match", etag);
  const response = await fetch(`/api/v1/sara/sessions/${sessionId}/state`, {
    method: "GET",
    credentials: "include",
    headers,
    signal
  });
  const nextEtag = response.headers.get("ETag") ?? etag;
  const retryAfterMs = parseRetryAfter(response.headers.get("Retry-After"));
  if (response.status === 304) {
    return { notModified: true, state: null, etag: nextEtag, retryAfterMs };
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw apiError(response);
  if (!validSessionState(data) || data.session_id !== sessionId) {
    throw new Error("Estado inválido do serviço SARA");
  }
  return { notModified: false, state: data, etag: nextEtag, retryAfterMs };
}

export function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.max(250, seconds * 1000);
  const date = Date.parse(value);
  if (!Number.isFinite(date)) return null;
  return Math.max(250, date - Date.now());
}

function csrf(): string {
  return decodeURIComponent(document.cookie.split("; ").find((value) => value.startsWith("ecos_csrf="))?.split("=")[1] ?? "");
}

function apiError(response: Response): ApiError {
  const message = response.status === 401
    ? "Sessão expirada. Entre novamente."
    : response.status === 429
      ? "Limite de interações atingido. Tente novamente mais tarde."
      : "SARA indisponível no momento.";
  return new ApiError(response.status, message, response.headers.get("Retry-After"));
}

function validRuntime(value: unknown): value is SaraRuntime {
  if (!value || typeof value !== "object") return false;
  const runtime = value as Partial<SaraRuntime>;
  return typeof runtime.state === "string"
    && runtimeStates.has(runtime.state)
    && typeof runtime.lifecycle_status === "string"
    && (runtime.stage === null || typeof runtime.stage === "string")
    && (runtime.active_engine === null || typeof runtime.active_engine === "string")
    && typeof runtime.progress === "number"
    && runtime.progress >= 0
    && runtime.progress <= 1
    && Number.isInteger(runtime.version)
    && typeof runtime.updated_at === "string"
    && (runtime.error_code === null || typeof runtime.error_code === "string");
}

function validResponse(value: unknown): value is SaraResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Partial<SaraResponse>;
  return typeof response.interaction_id === "string"
    && typeof response.response === "string"
    && response.response.length <= 10000
    && typeof response.session_id === "string"
    && validRuntime(response.runtime)
    && Array.isArray(response.ui_actions)
    && typeof response.unavailable === "boolean"
    && typeof response.incomplete_context === "boolean";
}

function validSessionState(value: unknown): value is SaraSessionState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<SaraSessionState>;
  return typeof state.session_id === "string" && validRuntime(state.runtime);
}
