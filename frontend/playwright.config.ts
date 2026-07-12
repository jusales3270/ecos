import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on-first-retry"
  },
  webServer: {
    command:
      "cd ../backend && UV_CACHE_DIR=/private/tmp/ecos-uv-cache uv run uvicorn --app-dir src ecos.main:app --host 127.0.0.1 --port 8000",
    url: "http://127.0.0.1:8000/health/live",
    reuseExistingServer: true,
    timeout: 30_000
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
