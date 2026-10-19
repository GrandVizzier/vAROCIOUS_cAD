import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/projects": api,
      "/build": api,
      "/download": api,
      "/sim": api, // also matches /simulate
      "/ws": { target: api, ws: true },
    },
  },
});
