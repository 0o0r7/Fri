import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    fs: { strict: false },
    proxy: {
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
      "/tc": {
        target: "https://technocore.chat",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/tc/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  publicDir: "public",
});
