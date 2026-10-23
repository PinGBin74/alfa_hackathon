import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В разработке /api проксируется на backend (uvicorn); в Docker это делает nginx (nginx.conf).
const api = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: { "/api": { target: api, changeOrigin: true, timeout: 600_000, proxyTimeout: 600_000 } },
  },
  preview: { port: 3000 },
});
