#!/usr/bin/env bash
# 启动前端：Vite dev server，默认端口 15173（偏僻端口），可用 VITE_PORT 覆盖。
# 默认直连后端 http://127.0.0.1:28123；如后端端口非默认，设置 VITE_LANGGRAPH_API_URL。
# 首次运行前请先在 frontend/ 下 npm install。
set -euo pipefail

cd "$(dirname "$0")/frontend"

# 依赖未安装时给出明确提示，而非 vite 报一堆错
if [ ! -d node_modules ]; then
  echo "未检测到 frontend/node_modules，请先运行：  cd frontend && npm install" >&2
  exit 1
fi

# Vite 读 VITE_PORT 环境变量覆盖 server.port（vite.config.ts 中已声明 port，--port 优先级更高）
exec npm run dev -- --port "${VITE_PORT:-15173}" "$@"
