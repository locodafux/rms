import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base is read at runtime from VITE_API_BASE (see src/api.ts); in dev we
// proxy /api to the FastAPI server so there are no CORS surprises.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // listen on 0.0.0.0 so a tunnel (ngrok) can reach it
    // Accept the tunnel's hostname (Vite blocks unknown hosts by default).
    // `true` allows any host — fine for a temporary ngrok demo.
    allowedHosts: true,
    proxy: {
      // Browser calls same-origin /api; Vite forwards to the backend server-side,
      // so tunneling only port 5173 also exposes the API. No CORS needed.
      "/api": "http://localhost:8000",
    },
  },
});
