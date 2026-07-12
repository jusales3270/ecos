import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./auth";
import { CommandPalette, SessionPipeline } from "./components";
import { LoginPage, OverviewPage } from "./pages";
import type { Overview } from "./types";

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

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: { get: () => null },
    json: () => Promise.resolve(payload)
  };
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
