import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./auth";
import { CommandPalette, SessionPipeline } from "./components";
import { ApprovalsPage, LoginPage, OverviewPage } from "./pages";
import type { Approval, AuthState, Overview } from "./types";

const unauthorizedFetch = vi.fn(() =>
  Promise.resolve({
    ok: false,
    status: 401,
    statusText: "Unauthorized",
    headers: { get: () => null },
    json: () => Promise.resolve({ error: { message: "authentication required" } })
  })
);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LoginPage", () => {
  it("renders browser authentication form and demo notice", () => {
    vi.stubGlobal("fetch", unauthorizedFetch);
    render(
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    );

    expect(screen.getByText("ECOS Operacional")).toBeInTheDocument();
    expect(screen.getByText(/Demo local/)).toBeInTheDocument();
  });
});

describe("CommandPalette", () => {
  it("navigates to the first filtered command from the keyboard", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <CommandPalette
                  commands={[
                    { id: "sessions", label: "Sessões", detail: "Ciclo", to: "/sessions" },
                    { id: "approvals", label: "Aprovações", detail: "Governança", to: "/approvals" }
                  ]}
                  onClose={() => undefined}
                  open
                />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.change(screen.getByLabelText("Buscar comando"), { target: { value: "apro" } });
    fireEvent.keyDown(screen.getByLabelText("Buscar comando"), { key: "Enter" });

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/approvals"));
  });
});

describe("SessionPipeline", () => {
  it("marks the approval stage as active when a session waits for approval", () => {
    render(
      <SessionPipeline
        currentStage="waiting_approval"
        stages={["context", "reasoning", "recommendation"]}
      />
    );

    expect(screen.getByText("Aprovação").closest("li")).toHaveClass("active");
    expect(screen.getByText("Recomendação").closest("li")).toHaveClass("complete");
  });
});

describe("OverviewPage states", () => {
  it("shows loading and then an empty cognitive workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(emptyOverview()))));

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByText("Carregando dados operacionais...")).toBeInTheDocument();
    expect(await screen.findByText("Nenhuma sessão cognitiva registrada.")).toBeInTheDocument();
  });

  it("shows API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
        status: 500,
        statusText: "Server Error",
        headers: { get: () => null },
        json: () => Promise.resolve({ error: { message: "overview unavailable" } })
      })
      )
    );

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("overview unavailable")).toBeInTheDocument();
  });
});

describe("ApprovalsPage governed flow", () => {
  it("renders pending and partially approved requests with quorum and runtime details", async () => {
    mockApprovalApi([
      approval(),
      approval({
        approval_id: "approval-partial",
        status: "partially_approved",
        approvals_recorded: 1
      })
    ]);

    renderApprovals();

    expect(await screen.findByText("pending")).toBeInTheDocument();
    expect(screen.getByText("partially_approved")).toBeInTheDocument();
    expect(screen.getByText("0 de 2 aprovações")).toBeInTheDocument();
    expect(screen.getByText("1 de 2 aprovações")).toBeInTheDocument();
    expect(screen.getByText("1 decisão ainda aguarda quorum.")).toBeInTheDocument();
    expect(screen.getAllByText("waiting_approval")).toHaveLength(2);
    expect(screen.getAllByText("executive_board")).toHaveLength(2);
  });

  it.each([
    ["Aprovar", "aprovar"],
    ["Rejeitar", "rejeitar"]
  ])("requires a reason before %s", async (buttonName, action) => {
    const fetchMock = mockApprovalApi([approval()]);
    renderApprovals();
    fireEvent.click(await screen.findByRole("button", { name: buttonName }));
    expect(screen.getByText(`Informe uma justificativa para ${action}.`)).toBeInTheDocument();
    expect(decisionCalls(fetchMock)).toHaveLength(0);
  });

  it.each([
    ["Aprovar", "approve"],
    ["Rejeitar", "reject"]
  ])("sends only reason and an idempotency key when choosing %s", async (buttonName, endpoint) => {
    const updated = approval({
      status: endpoint === "approve" ? "partially_approved" : "rejected",
      approvals_recorded: endpoint === "approve" ? 1 : 0,
      runtime_status: endpoint === "approve" ? "waiting_approval" : "error",
      error_code: endpoint === "reject" ? "RUNTIME_REJECTED" : null
    });
    const fetchMock = mockApprovalApi([approval()], updated);
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), {
      target: { value: "  revisão humana registrada  " }
    });
    fireEvent.click(screen.getByRole("button", { name: buttonName }));

    await waitFor(() => expect(decisionCalls(fetchMock)).toHaveLength(1));
    const [, options] = decisionCalls(fetchMock)[0];
    expect(String(decisionCalls(fetchMock)[0][0])).toContain(`/${endpoint}`);
    expect(JSON.parse(String(options?.body))).toEqual({ reason: "revisão humana registrada" });
    expect(new Headers(options?.headers).get("Idempotency-Key")).toMatch(
      new RegExp(`^approval\\.${endpoint}:`)
    );
    expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("keeps a partial approval active in waiting_approval", async () => {
    const partial = approval({ status: "partially_approved", approvals_recorded: 1 });
    mockApprovalApi([approval()], partial);
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Aprovo" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    expect(await screen.findByText("partially_approved")).toBeInTheDocument();
    expect(screen.getByText("waiting_approval")).toBeInTheDocument();
    expect(screen.queryByText("completed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aprovar" })).toBeEnabled();
  });

  it.each(["executing", "completed"] as const)(
    "reflects the final quorum runtime state %s",
    async (runtimeStatus) => {
      const final = approval({
        status: "approved",
        approvals_recorded: 2,
        runtime_status: runtimeStatus
      });
      mockApprovalApi([approval({ approvals_recorded: 1, status: "partially_approved" })], final);
      renderApprovals();
      fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Quorum final" } });
      fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
      expect(await screen.findByText(runtimeStatus)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Aprovar" })).toBeDisabled();
    }
  );

  it("reflects rejection as rejected/error/RUNTIME_REJECTED without execution", async () => {
    const rejected = approval({
      status: "rejected",
      runtime_status: "error",
      error_code: "RUNTIME_REJECTED",
      rejection_reason: "Risco residual"
    });
    const fetchMock = mockApprovalApi([approval()], rejected);
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Risco residual" } });
    fireEvent.click(screen.getByRole("button", { name: "Rejeitar" }));
    expect(await screen.findByText("rejected")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
    expect(screen.getByText(/Runtime rejeitado.*RUNTIME_REJECTED/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/executions"))).toBe(false);
  });

  it("disables both decisions while a request is in flight", async () => {
    let resolveDecision: ((response: ReturnType<typeof jsonResponse>) => void) | undefined;
    const fetchMock = mockApprovalApi([approval()]);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(authState()));
      if (url.endsWith("/approvals")) return Promise.resolve(jsonResponse([approval()]));
      return new Promise((resolve) => { resolveDecision = resolve; });
    });
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Em análise" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() => expect(resolveDecision).toBeDefined());
    expect(screen.getAllByRole("button", { name: "Registrando..." })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Registrando..." }).every((button) => button.hasAttribute("disabled"))).toBe(true);
    resolveDecision?.(jsonResponse(approval({ status: "approved", runtime_status: "completed", approvals_recorded: 2 })));
  });

  it("disables terminal, expired, already-decided and unauthorized requests", async () => {
    mockApprovalApi([
      approval({ approval_id: "approved", status: "approved", runtime_status: "completed" }),
      approval({ approval_id: "expired", expires_at: "2020-01-01T00:00:00Z" }),
      approval({ approval_id: "decided", decided_by: "user-approver" })
    ], undefined, authState({ permissions: [] }));
    renderApprovals();
    await screen.findByText("Acesso negado pela política da organização.");
    expect(screen.getAllByRole("button", { name: "Aprovar" }).every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getByText("Esta solicitação de aprovação expirou.")).toBeInTheDocument();
    expect(screen.getByText("Você já registrou uma decisão neste request.")).toBeInTheDocument();
  });

  it.each([
    [403, "Você não tem permissão"],
    [409, "Conflito: a decisão não foi registrada"],
    [410, "Esta solicitação de aprovação expirou"],
    [422, "A justificativa ou os dados da decisão são inválidos"]
  ])("handles HTTP %i without false success", async (status, expected) => {
    const fetchMock = mockApprovalApi([approval()], undefined, authState(), status);
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Decisão" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    expect(await screen.findByText(new RegExp(expected))).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/executions"))).toBe(false);
  });

  it("reports a network failure and preserves the legacy approval endpoint", async () => {
    const fetchMock = mockApprovalApi([approval({ runtime_status: null, required_roles: [] })]);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("auth/me")) return Promise.resolve(jsonResponse(authState()));
      if (url.endsWith("/approvals")) return Promise.resolve(jsonResponse([approval({ runtime_status: null, required_roles: [] })]));
      return Promise.reject(new Error("offline"));
    });
    renderApprovals();
    fireEvent.change(await screen.findByLabelText("Justificativa"), { target: { value: "Aprovação legada" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    expect(await screen.findByText(/Falha de rede.*offline/)).toBeInTheDocument();
    expect(String(decisionCalls(fetchMock)[0][0])).toContain("/api/v1/approvals/approval-1/approve");
  });
});

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 400 ? "Request failed" : "OK",
    headers: new Headers(),
    json: () => Promise.resolve(status >= 400 ? { error: { message: "backend decision error" } } : payload)
  };
}

function authState(overrides: Partial<AuthState["principal"]> = {}): AuthState {
  return {
    principal: {
      user_id: "user-approver",
      organization_id: "org-1",
      roles: ["executive_board"],
      permissions: ["sessions:read", "decisions:approve"],
      authentication_method: "cookie",
      session_id: null,
      token_id: null,
      issued_at: "2026-07-20T10:00:00Z",
      expires_at: "2026-07-20T12:00:00Z",
      correlation_id: "correlation-auth",
      ...overrides
    },
    organization: { organization_id: "org-1", name: "Acme" },
    demo: true
  };
}

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    approval_id: "approval-1",
    organization_id: "org-1",
    session_id: "session-1",
    recommendation_id: "recommendation-1",
    requester_id: "requester-1",
    requester_email: "requester@example.local",
    status: "pending",
    risks: ["risk-1"],
    plan: ["engine-1"],
    required_independent_approver: true,
    decided_by: null,
    decided_by_email: null,
    decided_at: null,
    rejection_reason: null,
    correlation_id: "correlation-1",
    created_at: "2026-07-20T10:00:00Z",
    action_scope: "runtime.execute",
    required_roles: ["executive_board"],
    minimum_approvals: 2,
    approvals_recorded: 0,
    expires_at: "2099-07-20T11:00:00Z",
    runtime_status: "waiting_approval",
    checkpoint_version: 1,
    error_code: null,
    ...overrides
  };
}

function mockApprovalApi(
  initial: Approval[],
  decision?: Approval,
  auth = authState(),
  errorStatus?: number
) {
  document.cookie = "ecos_csrf=csrf-test";
  let approvalGets = 0;
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("auth/me")) return Promise.resolve(jsonResponse(auth));
    if (url.endsWith("/approvals")) {
      approvalGets++;
      return Promise.resolve(jsonResponse(approvalGets > 1 && decision ? [decision] : initial));
    }
    if (errorStatus) return Promise.resolve(jsonResponse({}, errorStatus));
    return Promise.resolve(jsonResponse(decision ?? initial[0]));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function decisionCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([input]) => /\/(approve|reject)$/.test(String(input)));
}

function renderApprovals() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ApprovalsPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

function emptyOverview(): Overview {
  return {
    organization: { organization_id: "org-1", name: "Acme" },
    user: { user_id: "user-1", email: "operator@example.local", display_name: "Operator" },
    roles: ["operator"],
    permissions: ["sessions:read"],
    recent_sessions: [],
    sessions_by_status: {},
    pending_approvals: 0,
    running_executions: 0,
    approval_rate: 0,
    execution_success_rate: 0,
    average_recommendation_confidence: 0,
    recent_events: [],
    component_health: [{ component: "api", status: "healthy" }],
    observability: {}
  };
}
