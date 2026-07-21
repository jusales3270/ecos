import { expect, test } from "@playwright/test";

test("complete canonical cognitive cycle and reuse validated memory", async ({ page }) => {
  test.setTimeout(180_000);
  const objective = `Canonical homologation ${Date.now()}`;
  const requestedPaths: string[] = [];
  page.on("request", (request) => requestedPaths.push(new URL(request.url()).pathname));

  await page.goto("/login");
  await page.getByLabel("E-mail").fill("operator@demo.ecos.local");
  await page.getByLabel("Senha").fill("operator-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Cognitiva" })).toBeVisible();

  await page.getByRole("link", { name: "Sessões" }).click();
  await page.getByLabel("Objetivo da sessão").fill(objective);
  await page.getByLabel("Descrição da sessão").fill("Full canonical cognitive cycle");
  await page.getByRole("button", { name: "Criar sessão" }).click();
  await page.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);
  const firstSessionUrl = page.url();
  const firstSessionId = firstSessionUrl.split("/").at(-1) ?? "";
  await expect(page.getByRole("button", { name: "Iniciar cognição" })).toBeVisible();
  await page.getByRole("button", { name: "Iniciar cognição" }).click();
  await expect(page.getByText("waiting_approval", { exact: true })).toBeVisible({ timeout: 30_000 });

  for (const index of [1, 2, 3]) {
    await page.getByRole("button", { name: "Sair" }).click();
    await page.getByLabel("E-mail").fill(`board-${index}@demo.ecos.local`);
    await page.getByLabel("Senha").fill(`board-${index}-demo-password`);
    await page.getByRole("button", { name: "Entrar" }).click();
    await page.getByRole("link", { name: "Aprovações" }).click();
    const approval = page.locator(`[data-session-id="${firstSessionId}"] .panel`);
    await approval.getByLabel("Justificativa").fill(`Board review ${index}`);
    await approval.getByRole("button", { name: "Aprovar" }).click();
    await expect(approval.getByText(index < 3 ? "partially_approved" : "approved", { exact: true })).toBeVisible({ timeout: 30_000 });
  }

  await page.getByRole("link", { name: "Execuções" }).click();
  await expect(page.locator(`[data-session-id="${firstSessionId}"]`).getByText(/ExecutionResult/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Observações" }).click();
  await expect(page.locator(`[data-session-id="${firstSessionId}"]`).getByText(/ObservationResult/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Aprendizado" }).click();
  const learning = page.locator(`[data-session-id="${firstSessionId}"]`);
  const pendingReview = learning.locator('textarea[aria-label^="Justificativa"]');
  await pendingReview.fill("Approved for validated organizational reuse", { timeout: 30_000 });
  await learning.getByRole("button", { name: "Aprovar candidato" }).click();
  await expect(learning.getByText("completed", { exact: true })).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "Memória" }).click();
  await expect(page.getByRole("heading", { name: "Memória", exact: true })).toBeVisible();
  const memoryTitle = await page.locator(`[data-session-id="${firstSessionId}"] .panel h2`).first().textContent();
  expect(memoryTitle).toContain("Validated learning");

  await page.getByRole("button", { name: "Sair" }).click();
  await page.getByLabel("E-mail").fill("operator@demo.ecos.local");
  await page.getByLabel("Senha").fill("operator-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("link", { name: "Sessões" }).click();
  await page.getByLabel("Objetivo da sessão").fill(objective);
  await page.getByLabel("Descrição da sessão").fill("Reuse validated memory");
  await page.getByRole("button", { name: "Criar sessão" }).click();
  await page.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "Iniciar cognição" }).click();
  await expect(page.getByText(memoryTitle ?? "missing-memory-title")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Sair" }).click();
  await page.getByLabel("E-mail").fill("operator@tenant-b.ecos.local");
  await page.getByLabel("Senha").fill("tenant-b-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Cognitiva" })).toBeVisible({ timeout: 30_000 });
  await page.goto(firstSessionUrl);
  await expect(page.getByText("resource is not available")).toBeVisible({ timeout: 30_000 });

  expect(requestedPaths.some((path) => path.endsWith("/start"))).toBe(false);
  expect(requestedPaths).toContain("/api/v1/sara/interactions");
  expect(requestedPaths).toContain("/api/v1/observations");
  expect(requestedPaths).toContain("/api/v1/learning");
  expect(requestedPaths).toContain("/api/v1/memories");
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
