import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function response(payload: unknown) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: () => Promise.resolve(payload)
  };
}

describe("canonical cognitive API", () => {
  it("starts an existing session exclusively through SARA", async () => {
    const fetch = vi.fn((_path: RequestInfo | URL, _options?: RequestInit) =>
      Promise.resolve(response({ session_id: "session-1" }))
    );
    vi.stubGlobal("fetch", fetch);

    await api.startCognition("session-1");

    expect(fetch).toHaveBeenCalledOnce();
    const [path, options] = fetch.mock.calls[0]!;
    expect(path).toBe("/api/v1/sara/interactions");
    expect(options?.method).toBe("POST");
    expect(String(options?.body)).toContain('"session_id":"session-1"');
    expect(path).not.toContain("/sessions/session-1/start");
  });

  it("loads only canonical aggregates and validated memories", async () => {
    const fetch = vi.fn((_path: RequestInfo | URL, _options?: RequestInit) =>
      Promise.resolve(response([]))
    );
    vi.stubGlobal("fetch", fetch);

    await Promise.all([
      api.executions(),
      api.observations(),
      api.learning(),
      api.learningReviews(),
      api.memories()
    ]);

    expect(fetch.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/v1/executions",
      "/api/v1/observations",
      "/api/v1/learning",
      "/api/v1/learning/reviews",
      "/api/v1/memories"
    ]);
    expect(fetch.mock.calls.flat().join(" ")).not.toContain("/executions/");
  });
});
