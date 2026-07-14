import { afterEach, describe, expect, it, vi } from "vitest";
import { getSaraSessionState, parseRetryAfter, sendSaraInteraction } from "./saraApi";
import type { SaraRuntime, SaraRuntimeState } from "./saraTypes";

const sessionId = "10000000-0000-4000-8000-000000000999";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SARA API runtime contract", () => {
  it("creates an authenticated interaction and stores the strict response contract", async () => {
    document.cookie = "ecos_csrf=csrf-token";
    const payload = interaction("thinking");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(payload))));

    const result = await sendSaraInteraction("Analisar risco", [], null, "/sessions");

    expect(result).toEqual(payload);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/v1/sara/interactions");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-token");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toMatch(/^sara\.interact:/);
    expect(JSON.parse(String(init?.body))).toMatchObject({ message: "Analisar risco", session_id: null, route_context: "/sessions" });
  });

  it.each(["thinking", "waiting_approval", "executing", "completed", "error"] as SaraRuntimeState[])("accepts the backend-confirmed %s state", async (state) => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(interaction(state)))));
    await expect(sendSaraInteraction("Objetivo", [], null, "/")).resolves.toMatchObject({ runtime: { state } });
  });

  it("sends If-None-Match and reads ETag and Retry-After", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ session_id: sessionId, runtime: runtime("executing", 2) }, { ETag: '"checkpoint-2"', "Retry-After": "3" }))));

    const result = await getSaraSessionState(sessionId, '"checkpoint-1"', new AbortController().signal);

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(new Headers(init?.headers).get("If-None-Match")).toBe('"checkpoint-1"');
    expect(result).toEqual({ notModified: false, state: { session_id: sessionId, runtime: runtime("executing", 2) }, etag: '"checkpoint-2"', retryAfterMs: 3000 });
  });

  it("handles 304 without reading a body or manufacturing state", async () => {
    const json = vi.fn(() => Promise.reject(new Error("must not be called")));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 304, headers: new Headers({ ETag: '"checkpoint-2"', "Retry-After": "5" }), json } as unknown as Response)));

    await expect(getSaraSessionState(sessionId, '"checkpoint-2"', new AbortController().signal)).resolves.toEqual({ notModified: true, state: null, etag: '"checkpoint-2"', retryAfterMs: 5000 });
    expect(json).not.toHaveBeenCalled();
  });

  it("parses Retry-After seconds and rejects invalid values", () => {
    expect(parseRetryAfter("2")).toBe(2000);
    expect(parseRetryAfter("invalid")).toBeNull();
    expect(parseRetryAfter(null)).toBeNull();
  });
});

function runtime(state: SaraRuntimeState, version = 1): SaraRuntime {
  return { state, lifecycle_status: state, stage: null, active_engine: null, progress: state === "completed" ? 1 : 0, version, updated_at: "2026-07-13T12:00:00Z", error_code: state === "error" ? "runtime_failed" : null };
}

function interaction(state: SaraRuntimeState) {
  return { interaction_id: "interaction-1", session_id: sessionId, response: "Confirmado", runtime: runtime(state), ui_actions: [], incomplete_context: false, unavailable: false };
}

function jsonResponse(payload: unknown, headers?: HeadersInit): Response {
  return { ok: true, status: 200, headers: new Headers(headers), json: () => Promise.resolve(payload) } as Response;
}
