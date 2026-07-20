import type {
  Approval,
  AuthState,
  EventRecord,
  Execution,
  KnowledgeResult,
  OperationalSession,
  OutboxMessage,
  Overview,
  ReadinessInfo,
  VersionInfo
} from "./types";

export class ApiError extends Error {
  status: number;
  retryAfter: string | null;

  constructor(status: number, message: string, retryAfter: string | null = null) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

const csrfCookie = "ecos_csrf";

function csrfToken(): string | null {
  const match = document.cookie
    .split("; ")
    .find((item) => item.startsWith(`${csrfCookie}=`));
  return match ? decodeURIComponent(match.split("=")[1] ?? "") : null;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (options.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "include"
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.error?.message ?? message;
    } catch {
      message = response.statusText;
    }
    if (response.status === 409) {
      message = message || "Conflito de estado. Atualize e tente novamente.";
    }
    if (response.status === 401) {
      message = message || "Sessão expirada ou revogada. Entre novamente.";
    }
    if (response.status === 429) {
      const retry = response.headers.get("Retry-After");
      message = retry
        ? `Limite atingido. Tente novamente em ${retry}s.`
        : "Limite atingido. Tente novamente mais tarde.";
    }
    throw new ApiError(response.status, message, response.headers.get("Retry-After"));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function idempotencyKey(action: string): string {
  return `${action}:${crypto.randomUUID()}`;
}

export const api = {
  login: (email: string, password: string) =>
    request<AuthState>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password })
    }),
  logout: () => request<{ status: string }>("/api/v1/auth/logout", { method: "POST" }),
  me: () => request<AuthState>("/api/v1/auth/me"),
  overview: () => request<Overview>("/api/v1/overview"),
  sessions: (status = "") =>
    request<OperationalSession[]>(
      `/api/v1/sessions${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),
  createSession: (objective: string, description: string) =>
    request<OperationalSession>("/api/v1/sessions", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("session.create") },
      body: JSON.stringify({ objective, description })
    }),
  session: (id: string) => request<OperationalSession>(`/api/v1/sessions/${id}`),
  startCognition: (id: string) =>
    request<OperationalSession>(`/api/v1/sessions/${id}/start`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("session.start") }
    }),
  approvals: (status = "") =>
    request<Approval[]>(
      `/api/v1/approvals${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),
  approve: (id: string, reason: string) =>
    request<Approval>(`/api/v1/approvals/${id}/approve`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("approval.approve") },
      body: JSON.stringify({ reason })
    }),
  reject: (id: string, reason: string) =>
    request<Approval>(`/api/v1/approvals/${id}/reject`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("approval.reject") },
      body: JSON.stringify({ reason })
    }),
  executions: () => request<Execution[]>("/api/v1/executions"),
  startExecution: (id: string) =>
    request<Execution>(`/api/v1/executions/${id}/start`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("execution.start") }
    }),
  knowledge: (query: string) =>
    request<KnowledgeResult[]>(
      `/api/v1/knowledge/search?q=${encodeURIComponent(query)}`
    ),
  events: () => request<EventRecord[]>("/api/v1/events?limit=100"),
  audit: () => request<EventRecord[]>("/api/v1/audit"),
  members: () => request<Array<Record<string, unknown>>>("/api/v1/admin/members"),
  roles: () => request<string[]>("/api/v1/admin/roles"),
  permissions: () => request<string[]>("/api/v1/admin/permissions"),
  orgSettings: () => request<Record<string, unknown>>("/api/v1/admin/settings"),
  version: () => request<VersionInfo>("/health/version"),
  readiness: () => request<ReadinessInfo>("/api/v1/admin/readiness"),
  outbox: () => request<OutboxMessage[]>("/api/v1/admin/outbox"),
  reconcile: () =>
    request<Record<string, unknown>>("/api/v1/admin/reconcile", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey("admin.reconcile") }
    })
};
