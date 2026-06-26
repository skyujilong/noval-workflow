import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置：dev server 监听 5173，把 /api 代理到 langgraph dev 平台 (:8123)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // langgraph dev 平台 API 默认在 :8123，前端通过 /api 代理访问，避免浏览器 CORS
      "/api": {
        target: "http://127.0.0.1:8123",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
