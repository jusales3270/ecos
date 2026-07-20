import { expect, test } from "@playwright/test";

test("complete operational cycle with independent approval and audit", async ({
  page,
  request
}) => {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("operator@demo.ecos.local");
  await page.getByLabel("Senha").fill("operator-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Cognitiva" })).toBeVisible();

  await page.getByRole("link", { name: "Sessões" }).click();
  await page.getByRole("button", { name: "Criar sessão" }).click();
  await expect(page.getByRole("button", { name: "Iniciar cognição" })).toBeVisible();
  await page.getByRole("button", { name: "Iniciar cognição" }).click();
  await expect(page.getByText("Independent approval requested")).toBeVisible();
  await expect(
    page.getByText("Proceed with a bounded dry-run execution")
  ).toBeVisible();

  await page.getByRole("link", { name: "Aprovações" }).click();
  const requesterApproval = page.locator(".approval-board .panel").first();
  await requesterApproval.getByLabel("Justificativa").fill("Revisão do solicitante");
  await requesterApproval.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("Você não tem permissão para registrar esta decisão.")).toBeVisible();

  await page.getByRole("button", { name: "Sair" }).click();
  await page.getByLabel("E-mail").fill("approver@demo.ecos.local");
  await page.getByLabel("Senha").fill("approver-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("link", { name: "Aprovações" }).click();
  const independentApproval = page.locator(".approval-board .panel").first();
  await independentApproval.getByLabel("Justificativa").fill("Revisão independente concluída");
  await independentApproval.getByRole("button", { name: "Aprovar" }).click();
  await expect(independentApproval.getByText("approved", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Execuções" }).click();
  await page.locator("button:not([disabled])", { hasText: "Iniciar execução" }).first().click();
  await expect(page.getByText("Dry-run connector completed")).toBeVisible();
  await expect(page.getByText("safe validation path")).toBeVisible();

  await page.getByRole("link", { name: "Observabilidade" }).click();
  await expect(page.getByText("EXECUTION_COMPLETED")).toBeVisible();

  const login = await request.post("/api/v1/auth/login", {
    data: {
      email: "operator@tenant-b.ecos.local",
      password: "tenant-b-demo-password"
    }
  });
  expect(login.ok()).toBeTruthy();
  const setCookie =
    login
      .headersArray()
      .find((item) => item.name.toLowerCase() === "set-cookie")?.value ?? "";
  const crossTenant = await request.get(
    "/api/v1/sessions/10000000-0000-4000-8000-000000000999",
    { headers: { cookie: setCookie } }
  );
  expect(crossTenant.status()).toBe(403);

  await page.getByRole("button", { name: "Sair" }).click();
  await page.goto("/sessions");
  await expect(page.getByRole("heading", { name: "ECOS Operacional" })).toBeVisible();
});

test("governed runtime approval keeps partial quorum waiting and completes automatically", async ({ page }) => {
  let currentUser = "board-user-1";
  let approval = runtimeApproval();
  let finalListReads = 0;
  const calledPaths: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    calledPaths.push(path);
    if (path === "/api/v1/auth/me") {
      await route.fulfill({ json: runtimeAuth(currentUser) });
      return;
    }
    if (path === "/api/v1/approvals" && request.method() === "GET") {
      if (approval.runtime_status === "executing") {
        finalListReads++;
        if (finalListReads > 1) approval = { ...approval, runtime_status: "completed" };
      }
      await route.fulfill({ json: [approval] });
      return;
    }
    if (path.endsWith("/approve") && request.method() === "POST") {
      expect(request.postDataJSON()).toEqual({ reason: currentUser === "board-user-1" ? "Primeira revisão" : "Revisão final" });
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      approval = currentUser === "board-user-1"
        ? { ...approval, status: "partially_approved", approvals_recorded: 1, decided_by: currentUser }
        : { ...approval, status: "approved", approvals_recorded: 2, decided_by: currentUser, runtime_status: "executing" };
      await route.fulfill({ json: approval });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { message: "unexpected request" } } });
  });

  await page.goto("/approvals");
  await expect(page.getByText("pending")).toBeVisible();
  await expect(page.getByText("0 de 2 aprovações")).toBeVisible();
  await page.getByLabel("Justificativa").fill("Primeira revisão");
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("partially_approved")).toBeVisible();
  await expect(page.getByText("waiting_approval")).toBeVisible();
  await expect(page.getByText("1 de 2 aprovações")).toBeVisible();

  currentUser = "board-user-2";
  await page.reload();
  await page.getByLabel("Justificativa").fill("Revisão final");
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("executing")).toBeVisible();
  await expect(page.getByText("completed")).toBeVisible({ timeout: 5000 });
  expect(calledPaths.some((path) => path.includes("/executions"))).toBe(false);
});

test("governed runtime rejection ends in error without execution", async ({ page }) => {
  let approval = runtimeApproval({ approval_id: "runtime-rejection" });
  const calledPaths: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    calledPaths.push(path);
    if (path === "/api/v1/auth/me") {
      await route.fulfill({ json: runtimeAuth("board-rejector") });
      return;
    }
    if (path === "/api/v1/approvals" && request.method() === "GET") {
      await route.fulfill({ json: [approval] });
      return;
    }
    if (path.endsWith("/reject") && request.method() === "POST") {
      expect(request.postDataJSON()).toEqual({ reason: "Risco residual inaceitável" });
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      approval = {
        ...approval,
        status: "rejected",
        runtime_status: "error",
        error_code: "RUNTIME_REJECTED",
        rejection_reason: "Risco residual inaceitável",
        decided_by: "board-rejector"
      };
      await route.fulfill({ json: approval });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { message: "unexpected request" } } });
  });

  await page.goto("/approvals");
  await expect(page.getByText("pending")).toBeVisible();
  await page.getByLabel("Justificativa").fill("Risco residual inaceitável");
  await page.getByRole("button", { name: "Rejeitar" }).click();
  await expect(page.getByText("rejected", { exact: true })).toBeVisible();
  await expect(page.getByText("error", { exact: true })).toBeVisible();
  await expect(page.getByText(/RUNTIME_REJECTED/)).toBeVisible();
  expect(calledPaths.some((path) => path.includes("/executions"))).toBe(false);
});

function runtimeAuth(userId: string) {
  return {
    principal: {
      user_id: userId,
      organization_id: "org-runtime",
      roles: ["executive_board"],
      permissions: ["sessions:read", "decisions:approve"],
      authentication_method: "cookie",
      session_id: null,
      token_id: null,
      issued_at: "2026-07-20T10:00:00Z",
      expires_at: "2026-07-20T12:00:00Z",
      correlation_id: "auth-correlation"
    },
    organization: { organization_id: "org-runtime", name: "Runtime Org" },
    demo: true
  };
}

function runtimeApproval(overrides: Record<string, unknown> = {}) {
  return {
    approval_id: "runtime-approval",
    organization_id: "org-runtime",
    session_id: "runtime-session",
    recommendation_id: "runtime-plan",
    requester_id: "runtime-requester",
    requester_email: "requester@runtime.test",
    status: "pending",
    risks: ["GOVERNED_ACTION"],
    plan: ["governance", "execution"],
    required_independent_approver: true,
    decided_by: null,
    decided_by_email: null,
    decided_at: null,
    rejection_reason: null,
    correlation_id: "runtime-correlation",
    created_at: "2026-07-20T10:00:00Z",
    action_scope: "runtime.execute",
    required_roles: ["executive_board"],
    minimum_approvals: 2,
    approvals_recorded: 0,
    expires_at: "2099-07-20T12:00:00Z",
    runtime_status: "waiting_approval",
    checkpoint_version: 1,
    error_code: null,
    ...overrides
  };
}
