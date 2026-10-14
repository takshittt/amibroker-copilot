import { defineConfig, devices } from "@playwright/test";

/*
 * Drives the real site against the offline demo API: real checker,
 * database, Redis, quota and stream, with scripted answers in place of
 * OpenAI. Needs `make services-up`, and the dev database migrated and
 * indexed (`make db-migrate`, `make index FAKE=1`).
 */
const JWT_SECRET = "e2e-jwt-secret-that-is-at-least-32-bytes";
const BFF_KEY = "e2e-bff-key-that-is-at-least-32-bytes-long";
const API_PORT = 8011;
const WEB_PORT = 3211;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: "uv run python -m copilot.api.offline",
      cwd: "../api",
      url: `http://127.0.0.1:${API_PORT}/v1/health`,
      // The health check needs the key too, so any answer (401) means it is up.
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        OFFLINE_DEMO: "1",
        OFFLINE_PORT: String(API_PORT),
        DATABASE_URL:
          process.env.DATABASE_URL ?? "postgresql://copilot:copilot@localhost:5432/copilot_dev",
        REDIS_URL: "redis://localhost:6379/3",
        // Every test signs up; the normal limit of 5 an hour per address would stop the run.
        SIGNUPS_PER_IP_PER_HOUR: "1000",
        JWT_SECRET,
        BFF_SHARED_SECRET: BFF_KEY,
      },
    },
    {
      command: `pnpm next dev -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        API_URL: `http://127.0.0.1:${API_PORT}`,
        JWT_SECRET,
        BFF_SHARED_SECRET: BFF_KEY,
        SUPPORT_EMAIL: "help@example.in",
      },
    },
  ],
});
