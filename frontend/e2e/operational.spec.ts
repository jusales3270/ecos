import { expect, test } from "@playwright/test";

test("complete operational cycle with independent approval and audit", async ({
  page,
  request
}) => {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("operator@demo.ecos.local");
  await page.getByLabel("Senha").fill("operator-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();

  await page.getByRole("link", { name: "Sessões" }).click();
  await page.getByRole("button", { name: "Criar sessão" }).click();
  await expect(page.getByRole("button", { name: "Iniciar cognição" })).toBeVisible();
  await page.getByRole("button", { name: "Iniciar cognição" }).click();
  await expect(page.getByText("Independent approval requested")).toBeVisible();
  await expect(
    page.getByText("Proceed with a bounded dry-run execution")
  ).toBeVisible();

  await page.getByRole("link", { name: "Aprovações" }).click();
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("requester cannot approve")).toBeVisible();

  await page.getByRole("button", { name: "Sair" }).click();
  await page.getByLabel("E-mail").fill("approver@demo.ecos.local");
  await page.getByLabel("Senha").fill("approver-demo-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("link", { name: "Aprovações" }).click();
  await page.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText("approved")).toBeVisible();

  await page.getByRole("link", { name: "Execuções" }).click();
  await page.getByRole("button", { name: "Iniciar execução" }).click();
  await expect(page.getByText("Dry-run connector completed")).toBeVisible();
  await expect(page.getByText("safe validation path")).toBeVisible();

  await page.getByRole("link", { name: "Auditoria" }).click();
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
