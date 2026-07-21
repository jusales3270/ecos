import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8010",
    trace: "on-first-retry"
  },
  webServer: {
    command:
      "cd ../backend && ECOS_SESSION_REPOSITORY=postgres ECOS_MEMORY_REPOSITORY=postgres ECOS_OBSERVABILITY_REPOSITORY=postgres ECOS_KNOWLEDGE_REPOSITORY=postgres ECOS_SECURITY_REPOSITORY=postgres ECOS_OPERATIONAL_REPOSITORY=postgres ECOS_RUNTIME_CHECKPOINT_REPOSITORY=postgres UV_CACHE_DIR=/tmp/ecos-uv-cache uv run uvicorn --app-dir src ecos.main:app --host 127.0.0.1 --port 8010",
    url: "http://127.0.0.1:8010/health/live",
    reuseExistingServer: true,
    timeout: 180_000
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
