import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";

/**
 * 简单的变量插值解析：把字符串中的 ${VAR_NAME} 替换为 env 中对应的值。
 * 用于 .env 文件中的变量引用，如 VITE_LANGGRAPH_API_URL=http://127.0.0.1:${LANGGRAPH_PORT}
 */
function expandVars(value: string, env: Record<string, string>): string {
  return value.replace(/\$\{([A-Z0-9_]+)\}/g, (_, key) => {
    return env[key] ?? "";
  });
}

/**
 * 读取单个 .env 文件并解析为键值对
 */
function parseEnvFile(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  const content = fs.readFileSync(filePath, "utf-8");
  const result: Record<string, string> = {};
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const eqIndex = trimmed.indexOf("=");
    if (eqIndex === -1) {
      continue;
    }
    const key = trimmed.slice(0, eqIndex).trim();
    let value = trimmed.slice(eqIndex + 1).trim();
    // 去除引号（"value" 或 'value'）
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

/**
 * 按优先级顺序加载 .env 文件
 * 优先级（从低到高）：
 * 1. 根目录 .env
 * 2. frontend 目录 .env
 * 3. 根目录 .env.local
 * 4. frontend 目录 .env.local
 * 5. 根目录 .env.[mode]
 * 6. frontend 目录 .env.[mode]
 * 7. 根目录 .env.[mode].local
 * 8. frontend 目录 .env.[mode].local
 */
function loadEnvWithPriority(mode: string, rootDir: string, frontendDir: string): Record<string, string> {
  const envFiles = [
    path.join(rootDir, ".env"),
    path.join(frontendDir, ".env"),
    path.join(rootDir, ".env.local"),
    path.join(frontendDir, ".env.local"),
    path.join(rootDir, `.env.${mode}`),
    path.join(frontendDir, `.env.${mode}`),
    path.join(rootDir, `.env.${mode}.local`),
    path.join(frontendDir, `.env.${mode}.local`),
  ];

  let result: Record<string, string> = {};
  for (const file of envFiles) {
    const parsed = parseEnvFile(file);
    result = { ...result, ...parsed };
  }
  return result;
}

// Vite 配置：dev server 端口与 /api 代理目标均可通过环境变量配置。
// 兼容多 worktree 并行开发，避免端口冲突。
export default defineConfig(({ mode }) => {
  // 按正确优先级加载 .env 文件（.env.local 优先级高于 .env）
  // 使用 __dirname 确保路径解析正确（不受 npm run dev 工作目录影响）
  const frontendDir = __dirname;
  const rootDir = path.join(frontendDir, "..");
  const rawEnv = loadEnvWithPriority(mode, rootDir, frontendDir);

  // 解析变量插值（让 .env 中的 ${LANGGRAPH_PORT} 生效）
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(rawEnv)) {
    env[key] = expandVars(value, { ...process.env, ...rawEnv });
  }

  // 后端 langgraph dev 地址：优先 VITE_LANGGRAPH_API_URL，其次 LANGGRAPH_PORT + 默认 host，最终兜底 28123
  const langgraphPort = env.LANGGRAPH_PORT || "28123";
  const defaultApiUrl = `http://127.0.0.1:${langgraphPort}`;
  const apiUrl = env.VITE_LANGGRAPH_API_URL || defaultApiUrl;

  // 前端 dev server 端口：优先 VITE_PORT，兜底 15173
  const port = parseInt(env.VITE_PORT || "15173", 10);

  return {
    plugins: [react()],
    // 把 env 变量注入给前端代码（import.meta.env.*）
    define: {
      "import.meta.env.VITE_LANGGRAPH_PORT": JSON.stringify(env.LANGGRAPH_PORT),
      "import.meta.env.VITE_LANGGRAPH_API_URL": JSON.stringify(apiUrl),
    },
    server: {
      port,
      proxy: {
        // langgraph dev 平台 API，前端通过 /api 代理访问，避免浏览器 CORS
        "/api": {
          target: apiUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
