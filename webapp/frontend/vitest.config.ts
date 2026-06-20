import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vitest configuration kept separate from vite.config.ts so the test
// environment (jsdom) and fast-check property tests (tasks 16.2, 19.2) and
// component tests have a clear place to run.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // Property-based tests run a minimum of 100 iterations; give them room.
    testTimeout: 30_000,
  },
});
