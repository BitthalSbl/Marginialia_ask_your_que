import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: /api is proxied to FastAPI. Build: output goes into backend/static, which FastAPI serves
// from the same origin (so production needs no CORS and no VITE_API_URL).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/static", emptyOutDir: true },
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
