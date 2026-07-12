import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./auth";
import { LoginPage } from "./pages";

vi.stubGlobal(
  "fetch",
  vi.fn(() =>
    Promise.resolve({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: () => Promise.resolve({ error: { message: "authentication required" } })
    })
  )
);

describe("LoginPage", () => {
  it("renders browser authentication form and demo notice", () => {
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
