import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors the "@/*" path alias in tsconfig, so tests import modules by
    // the same specifier the application does.
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    // happy-dom over jsdom: markedly faster startup, and nothing here
    // needs jsdom's fuller (slower) DOM implementation.
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Playwright drives the browser; Vitest must not try to run those.
    exclude: ["**/node_modules/**", "**/e2e/**", "**/.next/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        // shadcn primitives are vendored, not authored here.
        "src/components/ui/**",
        "src/app/**/layout.tsx",
      ],
      // Deliberately no thresholds yet. Same reasoning as the backend:
      // a number picked before the trend is known either blocks every PR
      // or means nothing. Measure first, then set a floor just under the
      // observed minimum.
    },
  },
});
