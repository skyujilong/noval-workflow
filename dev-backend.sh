#!/usr/bin/env bash
# 启动后端：langgraph dev（图 noval_workflow + http_app.py 静态服务）
# 默认端口 28123（偏僻端口，避免与本地其他服务冲突），可用 LANGGRAPH_PORT 覆盖。
# 用项目 venv，从仓库根目录启动以保证 ./output 等相对路径正确。
#
# 前端 API_URL 默认指向 :28123；改此端口时需同步 frontend/src/lib/langgraph.ts
# 与 frontend/vite.config.ts 的 proxy target，或设置 VITE_LANGGRAPH_API_URL。
set -euo pipefail

cd "$(dirname "$0")"

PORT="${LANGGRAPH_PORT:-28123}"
exec .venv/bin/langgraph dev --port "$PORT" "$@"
