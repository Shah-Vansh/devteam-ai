/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // One shared .env at the repository root (ADR 0010). Vite only exposes variables that
  // start with VITE_, so backend secrets in the same file never reach the browser.
  envDir: "..",
  server: { port: 5173, strictPort: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ belongs to Playwright
    css: false,
  },
});
