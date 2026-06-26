import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 配置：dev server 监听 15173，把 /api 代理到 langgraph dev 平台 (:28123)
// 端口与 dev-backend.sh / src/lib/langgraph.ts 保持一致；改端口时三处同步。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 15173,
    proxy: {
      // langgraph dev 平台 API 在 :28123，前端通过 /api 代理访问，避免浏览器 CORS
      "/api": {
        target: "http://127.0.0.1:28123",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
