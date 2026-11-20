import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real dashboard in a browser against a mocked backend (every
// /api request is answered by the test), so they need no LLM, sandbox or database.
// Locally they use the installed Microsoft Edge; CI uses Playwright's own Chromium.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "browser",
      use: { ...devices["Desktop Chrome"], channel: process.env.CI ? undefined : "msedge" },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
