/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Project Sentinel Dashboard frontend.
//
// Dev server (port 5173) proxies /api/* to the Flask backend on port 5001
// (req 2.1). In production Flask serves the built bundle from `dist/` at the
// same origin, so relative `/api/...` URLs work in both modes — no env vars.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:5001",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
