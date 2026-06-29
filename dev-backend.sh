#!/usr/bin/env bash
# 启动后端：langgraph dev（图 noval_workflow + http_app.py 静态服务）
# 默认端口 28123（偏僻端口，避免与本地其他服务冲突）。
# 端口优先从 .env / .env.local 的 LANGGRAPH_PORT 读取，也可命令行 LANGGRAPH_PORT=xxx 覆盖。
# 用项目 venv，从仓库根目录启动以保证 ./output 等相对路径正确。
#
# 多 worktree 并行开发时：在各自的 .env.local 中设置不同 LANGGRAPH_PORT 与 VITE_PORT，
# VITE_LANGGRAPH_API_URL 自动通过 ${LANGGRAPH_PORT} 变量插值同步，无需手动改两处。
set -euo pipefail

cd "$(dirname "$0")"

# 加载 .env（如存在）；命令行显式设置的优先级更高
if [ -f .env ]; then
  set -a; . .env; set +a
fi
if [ -f .env.local ]; then
  set -a; . .env.local; set +a
fi

PORT="${LANGGRAPH_PORT:-28123}"
exec .venv/bin/langgraph dev --port "$PORT" "$@"
