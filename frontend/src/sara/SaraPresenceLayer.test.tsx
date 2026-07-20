import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { useAuth } from "../auth";
import { isSaraAction } from "./saraActions";
import { SaraPresenceLayer } from "./SaraPresenceLayer";
import { loadSaraPreferences, saraStorageKey } from "./saraStorage";
import type { SaraResponse, SaraRuntime, SaraRuntimeState } from "./saraTypes";

const auth = { principal: { user_id: "user-1", organization_id: "org-1", roles: [], permissions: ["sessions:write"], authentication_method: "cookie", session_id: null, token_id: null, issued_at: "", expires_at: "", correlation_id: "corr" }, organization: { organization_id: "org-1", name: "Acme" }, demo: true };
const sessionId = "10000000-0000-4000-8000-000000000999";
const response = interaction("completed");

beforeEach(() => { localStorage.clear(); vi.stubGlobal("SpeechSynthesisUtterance", class { lang = ""; onstart: (() => void) | null = null; onend: (() => void) | null = null; onerror: (() => void) | null = null; constructor(public text: string) {} }); vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(jsonResponse(String(input).includes("auth/me") ? auth : response)))); Object.defineProperty(window, "speechSynthesis", { configurable: true, value: { cancel: vi.fn(), speak: vi.fn(), getVoices: vi.fn(() => []) } }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("SaraPresenceLayer", () => {
  it("invokes, minimizes, closes and restores persisted mode", async () => {
    const { unmount } = renderLayer(); expect(await screen.findByLabelText("Invocar SARA")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Invocar SARA")); expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Minimizar SARA")); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount(); renderLayer(); expect(screen.queryByLabelText("Invocar SARA")).not.toBeInTheDocument();
    await screen.findByLabelText("Presença SARA"); const restoredStage = document.querySelector(".sh-stage")!; fireEvent.pointerDown(restoredStage, { pointerId: 1, clientX: 20, clientY: 20 }); fireEvent.pointerUp(restoredStage, { pointerId: 1, clientX: 20, clientY: 20 }); fireEvent.click(screen.getByLabelText("Fechar SARA")); expect(screen.getByLabelText("Invocar SARA")).toBeInTheDocument();
  });
  it("sends text through the authenticated API and handles failure", async () => {
    renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA"));
    fireEvent.change(screen.getByLabelText("Objetivo ou interação cognitiva"), { target: { value: "Analisar risco" } }); fireEvent.click(screen.getByLabelText("Enviar interação"));
    expect(await screen.findByText("Objetivo registrado.")).toBeInTheDocument();
    const root = document.querySelector(".sh-root");
    expect(root).toHaveAttribute("data-session-id", sessionId);
    expect(root).toHaveAttribute("data-interaction-id", "interaction-1");
    expect(root).toHaveAttribute("data-runtime-state", "completed");
    vi.mocked(fetch).mockRejectedValueOnce(new Error("SARA offline")); fireEvent.change(screen.getByLabelText("Objetivo ou interação cognitiva"), { target: { value: "Tentar novamente" } }); fireEvent.click(screen.getByLabelText("Enviar interação")); expect(await screen.findByText("SARA offline")).toBeInTheDocument();
  });
  it("reports unavailable speech recognition", async () => {
    renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA")); fireEvent.click(screen.getByLabelText("Usar microfone")); expect(screen.getByText(/reconhecimento de voz não está disponível/)).toBeInTheDocument();
  });
  it("handles an expired authenticated session", async () => {
    renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA")); vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 401, statusText: "Unauthorized", headers: new Headers(), json: () => Promise.resolve({}) } as Response); fireEvent.change(screen.getByLabelText("Objetivo ou interação cognitiva"), { target: { value: "Continuar" } }); fireEvent.click(screen.getByLabelText("Enviar interação")); expect(await screen.findByText("Sessão expirada. Entre novamente.")).toBeInTheDocument();
  });
  it("renders with reduced motion enabled", async () => {
    Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: true, addEventListener: () => undefined, removeEventListener: () => undefined }) }); renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA")); expect(document.querySelector("canvas")).toBeInTheDocument();
  });
  it("supports keyboard invocation and escape minimization without capturing inputs", async () => {
    renderLayer(); await screen.findByLabelText("Invocar SARA"); fireEvent.keyDown(window, { key: "s", altKey: true }); expect(screen.getByRole("dialog")).toBeInTheDocument(); fireEvent.keyDown(window, { key: "Escape" }); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("moves the whole mini widget and persists a bounded position", async () => {
    renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA")); fireEvent.click(screen.getByLabelText("Minimizar SARA")); const stage = document.querySelector(".sh-stage")!; fireEvent.pointerDown(stage, { pointerId: 1, clientX: 20, clientY: 20 }); fireEvent.pointerMove(stage, { pointerId: 1, clientX: 90, clientY: 80 }); fireEvent.pointerUp(stage, { pointerId: 1, clientX: 90, clientY: 80 }); expect(loadSaraPreferences("org-1", "user-1").position.x).toBeGreaterThan(24);
  });
  it("cancels speech and animation resources on cleanup", async () => { const cancel = vi.spyOn(window, "cancelAnimationFrame"); const view = renderLayer(); fireEvent.click(await screen.findByLabelText("Invocar SARA")); view.unmount(); expect(cancel).toHaveBeenCalled(); expect(window.speechSynthesis.cancel).toHaveBeenCalled(); });
  it("uses organization and user isolated storage", () => { expect(saraStorageKey("a", "u")).not.toBe(saraStorageKey("b", "u")); });
});

describe("SARA runtime integration", () => {
  it.each(["thinking", "waiting_approval", "executing", "completed", "error"] as SaraRuntimeState[])("stores the confirmed %s state", async (runtimeState) => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (String(input).includes("/interactions")) return Promise.resolve(jsonResponse(interaction(runtimeState)) as Response);
      return new Promise<Response>(() => undefined);
    });
    const view = renderLayer();
    await submit("Confirmar estado");
    await waitFor(() => expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", runtimeState));
    view.unmount();
  });

  it("polls once per session and stops after a confirmed terminal state", async () => {
    let stateCalls = 0;
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (url.includes("/interactions")) return Promise.resolve(jsonResponse(interaction("thinking")) as Response);
      stateCalls++;
      return Promise.resolve(jsonResponse({ session_id: sessionId, runtime: runtime("completed", 2) }, { ETag: '"2"' }) as Response);
    });
    renderLayer();
    await submit("Executar fluxo");
    await waitFor(() => expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", "completed"));
    expect(stateCalls).toBe(1);
  });

  it.each(["completed", "error"] as SaraRuntimeState[])("does not regress or poll after terminal %s", async (terminalState) => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (url.includes("/interactions")) return Promise.resolve(jsonResponse(interaction(terminalState)) as Response);
      return Promise.resolve(jsonResponse({ session_id: sessionId, runtime: runtime("waiting_approval", 1) }) as Response);
    });
    renderLayer();
    await submit("Estado terminal");
    await waitFor(() => expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", terminalState));
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    expect(countStateRequests()).toBe(0);
    expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", terminalState);
  });

  it("keeps the last confirmed visual state after a 304 response", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (url.includes("/interactions")) return Promise.resolve(jsonResponse(interaction("waiting_approval")) as Response);
      return Promise.resolve(notModifiedResponse({ ETag: '"1"', "Retry-After": "60" }));
    });
    renderLayer();
    await submit("Aguardar aprovação");
    await waitFor(() => expect(countStateRequests()).toBe(1));
    expect(screen.getByText("AGUARDANDO APROVAÇÃO")).toBeInTheDocument();
    expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", "waiting_approval");
  });

  it("aborts polling on unmount", async () => {
    let pollSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (url.includes("/interactions")) return Promise.resolve(jsonResponse(interaction("executing")) as Response);
      pollSignal = init?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    });
    const view = renderLayer();
    await submit("Monitorar execução");
    await waitFor(() => expect(pollSignal).toBeDefined());
    view.unmount();
    expect(pollSignal?.aborted).toBe(true);
  });

  it("prevents an old session response from replacing a newer session", async () => {
    const newerSession = "20000000-0000-4000-8000-000000000999";
    let postCalls = 0;
    let resolveOldPoll: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      if (url.includes("/interactions")) {
        postCalls++;
        return Promise.resolve(jsonResponse(interaction(postCalls === 1 ? "waiting_approval" : "completed", postCalls === 1 ? sessionId : newerSession)) as Response);
      }
      return new Promise<Response>((resolve) => { resolveOldPoll = resolve; });
    });
    renderLayer();
    await submit("Primeira sessão");
    await waitFor(() => expect(resolveOldPoll).toBeDefined());
    await submit("Nova sessão");
    await waitFor(() => expect(document.querySelector(".sh-root")).toHaveAttribute("data-session-id", newerSession));
    resolveOldPoll?.(jsonResponse({ session_id: sessionId, runtime: runtime("error", 9) }) as Response);
    await Promise.resolve();
    expect(document.querySelector(".sh-root")).toHaveAttribute("data-session-id", newerSession);
    expect(document.querySelector(".sh-root")).toHaveAttribute("data-runtime-state", "completed");
  });

  it("ignores unauthorized actions and never calls approval or execution endpoints", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("auth/me")) return Promise.resolve(jsonResponse(auth) as Response);
      return Promise.resolve(jsonResponse({ ...interaction("completed"), ui_actions: [{ type: "approve" }, { type: "start_execution" }, { type: "navigate", route: "https://evil.test" }] }) as Response);
    });
    renderLayer();
    await submit("Sem automação");
    await screen.findByText("Objetivo registrado.");
    const urls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => /approve|start_execution/.test(url))).toBe(false);
    expect(screen.getByTestId("route")).toHaveTextContent("/");
  });
});

describe("SARA action whitelist", () => { it("accepts known actions and rejects scripts, DOM selectors and external URLs", () => { expect(isSaraAction({ type: "open_approvals" })).toBe(true); expect(isSaraAction({ type: "navigate", route: "/governance" })).toBe(false); expect(isSaraAction({ type: "navigate", route: "https://evil.test" })).toBe(false); expect(isSaraAction({ type: "javascript", code: "alert(1)" })).toBe(false); }); });

function renderLayer() { return render(<MemoryRouter><AuthProvider><AuthenticatedSara /><Location /></AuthProvider></MemoryRouter>); }
function AuthenticatedSara() { const { auth } = useAuth(); return auth ? <SaraPresenceLayer /> : null; }
function Location() { return <span data-testid="route">{useLocation().pathname}</span>; }
async function submit(message: string) { let input = screen.queryByLabelText("Objetivo ou interação cognitiva"); if (!input) { fireEvent.click(await screen.findByLabelText("Invocar SARA")); input = await screen.findByLabelText("Objetivo ou interação cognitiva"); } fireEvent.change(input, { target: { value: message } }); fireEvent.click(screen.getByLabelText("Enviar interação")); }
function runtime(state: SaraRuntimeState, version = 1): SaraRuntime { return { state, lifecycle_status: state === "error" ? "failed" : state, stage: state === "completed" ? null : "orchestration", active_engine: state === "executing" ? "execution" : null, progress: state === "completed" ? 1 : 0, version, updated_at: "2026-07-13T12:00:00Z", error_code: state === "error" ? "runtime_failed" : null }; }
function interaction(state: SaraRuntimeState, currentSessionId = sessionId): SaraResponse { return { interaction_id: "interaction-1", response: "Objetivo registrado.", session_id: currentSessionId, runtime: runtime(state), ui_actions: [], unavailable: false, incomplete_context: true }; }
function jsonResponse(payload: unknown, headers?: HeadersInit) { return { ok: true, status: 200, statusText: "OK", headers: new Headers(headers), json: () => Promise.resolve(payload) }; }
function notModifiedResponse(headers?: HeadersInit): Response { return { ok: false, status: 304, statusText: "Not Modified", headers: new Headers(headers), json: () => Promise.reject(new Error("304 must not parse JSON")) } as Response; }
function countStateRequests(): number { return vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes("/state")).length; }
