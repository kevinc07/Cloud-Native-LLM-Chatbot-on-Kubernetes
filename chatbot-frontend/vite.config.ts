import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 本機開發:前端 :5173,把 API 路徑代理到 VITE_DEV_BACKEND(預設本機 backend :8000)。
// 部署後前端與 API 同一個網址(同源),不需要代理,也不需要把網址烤進 image。
const backend = process.env.VITE_DEV_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  // 輸出到 build/,Dockerfile 與 .dockerignore 沿用 CRA 時期的路徑
  build: { outDir: "build" },
  server: {
    proxy: {
      "/chat": { target: backend, changeOrigin: true },
      "/conversations": { target: backend, changeOrigin: true },
      "/health": { target: backend, changeOrigin: true },
    },
  },
});
