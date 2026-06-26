# 小说创作工作台 UI

基于 LangGraph 平台 API 的自定义 Web UI，替代官方 LangGraph Studio 用于本工作流。
提供：节点图可视化、小说（thread）选择、历史回溯、interrupt 表单交互。

## 架构

- 前端：React + Vite + React Flow + Tailwind + `@langchain/langgraph-sdk`
- 后端：复用 `langgraph dev` 平台 API（**零后端 Python 改动**）
- 一个「小说」= 一个 LangGraph thread，`novel_name` 存于 thread metadata

## 启动

```bash
# 1. 后端（项目根目录）
.venv/bin/langgraph dev --port 8123

# 2. 前端（本目录）
npm install
npm run dev
# 默认 5173；若被占用会自动换端口（看终端输出）
```

打开浏览器访问 vite 提示的本地地址（如 http://localhost:5173 ）。

> 前端直连 `http://127.0.0.1:8123`。如需改地址，设置环境变量 `VITE_LANGGRAPH_API_URL`。

## 使用

1. 左侧「小说」面板 → 点「+ 新建」→ 自动启动 run，停在 `collect_user_inputs`
2. 右侧表单填 7 个创作参数 → 提交 → graph 推进到首个审稿节点
3. 审稿表单：查看草稿 →「通过」或「提出修改意见」→ 继续推进
4. 中部节点图实时高亮当前执行节点
5. 左侧切「历史」面板 → 查看 checkpoint 快照 → 可「从此点分叉」

## interrupt 表单与 resume 值

各中断点的 payload 结构与 resume 值格式见 `src/lib/interruptTypes.ts`（已从源码核实）。
分发逻辑在 `src/components/interrupts/InterruptHandler.tsx`，按 payload 结构化字段判别。

注意：`human_review` 的草稿从 interrupt `message` 的 `\n\n---\n` 之前部分解析
（草稿在子图 state 中，父 thread state 不暴露）。`review_type` 从父 state 取。

## 部署

MVP 用 `langgraph dev` + `npm run dev` 即可（无 Docker，数据持久化在本地 `.langgraph_api/`）。
后续如需常驻服务：后端 `langgraph build && langgraph up`（Docker），前端 `npm run build` 后用 nginx 托管。
