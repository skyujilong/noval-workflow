#!/usr/bin/env bash
# 启动前端：Vite dev server，默认端口 15173（偏僻端口）。
# 端口优先从 .env / .env.local 的 VITE_PORT 读取，也可命令行 VITE_PORT=xxx 覆盖。
# 后端 API 地址：VITE_LANGGRAPH_API_URL，.env 中支持 ${LANGGRAPH_PORT} 变量插值自动同步。
# 首次运行前请先在 frontend/ 下 npm install。
set -euo pipefail

cd "$(dirname "$0")"

# 加载根目录 .env（如存在）；命令行显式设置的优先级更高
if [ -f .env ]; then
  set -a; . .env; set +a
fi
if [ -f .env.local ]; then
  set -a; . .env.local; set +a
fi

cd frontend

# 依赖未安装时给出明确提示，而非 vite 报一堆错
if [ ! -d node_modules ]; then
  echo "未检测到 frontend/node_modules，请先运行：  cd frontend && npm install" >&2
  exit 1
fi

# Vite 读 VITE_PORT 环境变量覆盖 server.port（vite.config.ts 中已声明 port，--port 优先级更高）
exec npm run dev -- --port "${VITE_PORT:-15173}" "$@"
