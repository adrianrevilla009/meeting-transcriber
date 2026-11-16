import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// En desarrollo, /api se redirige a la API local (igual que hace nginx en Docker).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      // Asistente en vivo (módulo 3), también bajo el mismo origen.
      "/assistant": {
        target: "http://127.0.0.1:8200",
        rewrite: (p) => p.replace(/^\/assistant/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    coverage: { provider: "v8", include: ["src/**"], exclude: ["src/test/**", "src/main.tsx", "src/**/*.test.*"] },
  },
});
