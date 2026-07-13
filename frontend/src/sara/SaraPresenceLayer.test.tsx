import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth";
import { useAuth } from "../auth";
import { isSaraAction } from "./saraActions";
import { SaraPresenceLayer } from "./SaraPresenceLayer";
import { loadSaraPreferences, saraStorageKey } from "./saraStorage";

const auth = { principal: { user_id: "user-1", organization_id: "org-1", roles: [], permissions: ["sessions:write"], authentication_method: "cookie", session_id: null, token_id: null, issued_at: "", expires_at: "", correlation_id: "corr" }, organization: { organization_id: "org-1", name: "Acme" }, demo: true };
const response = { response: "Objetivo registrado.", session_id: "10000000-0000-4000-8000-000000000999", cognitive_state: "created", ui_actions: [], unavailable: false, incomplete_context: true };

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

describe("SARA action whitelist", () => { it("accepts known actions and rejects scripts, DOM selectors and external URLs", () => { expect(isSaraAction({ type: "open_approvals" })).toBe(true); expect(isSaraAction({ type: "navigate", route: "/governance" })).toBe(true); expect(isSaraAction({ type: "navigate", route: "https://evil.test" })).toBe(false); expect(isSaraAction({ type: "javascript", code: "alert(1)" })).toBe(false); }); });

function renderLayer() { return render(<MemoryRouter><AuthProvider><AuthenticatedSara /><Location /></AuthProvider></MemoryRouter>); }
function AuthenticatedSara() { const { auth } = useAuth(); return auth ? <SaraPresenceLayer /> : null; }
function Location() { return <span data-testid="route">{useLocation().pathname}</span>; }
function jsonResponse(payload: unknown) { return { ok: true, status: 200, statusText: "OK", headers: new Headers(), json: () => Promise.resolve(payload) }; }
