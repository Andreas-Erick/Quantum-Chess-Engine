import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API = process.env.QC_API_URL ?? "http://localhost:8000";
const apiRoutes = [
  "/init",
  "/do_move",
  "/state",
  "/legal_moves",
  "/ai_move",
  "/correlations",
  "/levels",
  "/online",
  "/health",
];

export default defineConfig({
  plugins: [react()],
  server: {
    // During development the UI runs on :5173 and forwards API calls to uvicorn.
    proxy: {
      ...Object.fromEntries(apiRoutes.map((route) => [route, API])),
      "/ws": { target: API, ws: true },
    },
  },
});
