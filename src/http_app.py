"""自定义 HTTP 路由：挂载 output 目录为静态文件服务 + 按小说的提示词覆盖读写接口。

通过 langgraph.json 的 http.app 配置加载，与平台 API 同端口（默认 8123）合并、
无前缀。前端经 <API_URL>/output/<小说名>/chapters/*.txt 读取章节正文；经
<API_URL>/prompt-overrides 读写该小说的提示词覆盖（覆盖题材风味字段）。

目录解析相对于 langgraph dev 的启动 cwd（项目根），默认 ./output；
可用 NOVEL_OUTPUT_DIR 环境变量覆盖（与 noval_workflow.context.get_output_dir 一致）。

注意：langgraph_api 运行时只安装了 starlette（无 fastapi），故此处用 Starlette。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import fields

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

# output 根目录：与 context.get_output_dir 保持同一来源
_output_dir = os.environ.get("NOVEL_OUTPUT_DIR", "./output")

# 挂载前确保目录存在：StaticFiles 构造时会校验 directory，缺失会抛 RuntimeError，
# 导致整个 langgraph dev 启动失败。./output 是工作流输出根目录，首启时尚未被创建，
# 这里无条件建空目录（exist_ok=True 幂等），不影响后续 save_chapter 等正常写入。
os.makedirs(_output_dir, exist_ok=True)


# ── 提示词覆盖接口 ───────────────────────────────────────────────────────────────
# 覆盖项粒度为 GenreFlavor 字段；存储不入 langgraph state，放在每本小说输出目录下的
# prompt_overrides.json（key = 安全小说名，与 config.json 同目录），每次节点运行新鲜读取。

async def get_prompt_overrides(request: Request) -> JSONResponse:
    """返回某小说的题材默认值（供前端预填）与已存覆盖项。

    query: novel=<原始小说名>, genre=<题材>
    resp:  {"defaults": {字段: 题材默认值...}, "overrides": {已存覆盖...}}
    """
    # 惰性 import：避免 http_app 模块加载期与图模块的导入顺序耦合
    from noval_workflow.prompts import GenreFlavor, get_prompt_pack, load_overrides

    novel = request.query_params.get("novel", "")
    genre = request.query_params.get("genre", "")
    # 不传 novel_name 取得纯题材基础包，导出全字段默认值（前端无需硬编码字段集）
    pack = get_prompt_pack(genre)
    defaults = {f.name: getattr(pack.flavor, f.name) for f in fields(GenreFlavor)}
    # load_overrides 读盘是同步阻塞调用，放到线程里执行，避免阻塞 ASGI 事件循环
    overrides = await asyncio.to_thread(load_overrides, novel) if novel else {}
    return JSONResponse({"defaults": defaults, "overrides": overrides})


async def put_prompt_overrides(request: Request) -> JSONResponse:
    """保存某小说的提示词覆盖。

    query: novel=<原始小说名>
    body:  {"overrides": {字段: 文本...}}（仅含与默认不同的字段；后端再做安全过滤）
    """
    from noval_workflow.prompts import save_overrides

    novel = request.query_params.get("novel", "")
    if not novel:
        return JSONResponse({"error": "missing novel"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    overrides = body.get("overrides", {}) if isinstance(body, dict) else {}
    if not isinstance(overrides, dict):
        overrides = {}
    # save_overrides 做 mkdir + write_text，同步阻塞，放到线程里执行避免阻塞事件循环
    saved = await asyncio.to_thread(save_overrides, novel, overrides)
    return JSONResponse({"ok": True, "overrides": saved})


# ── 小说列表摘要接口（轻量化轮询） ───────────────────────────────────────────────
# 平台 POST /threads/search 会为每个 thread 返回完整 values（整个 NovelState，含正文/大纲
# /人物档案等大字段）。前端列表 3s 轮询只需 novel_name / total_chapters_written / status，
# 全量拉取使单次 payload 达数百 KB。此接口在服务端自调用平台 search 后把 values 裁成白名单，
# 结构与 search 一致（仅 values 变小），前端可零成本映射，payload 降到几 KB。

# 列表/配置抽屉实际读到的 values 字段（均为 state.py 里的小标量），其余大字段一律不返回。
_SUMMARY_VALUE_FIELDS = ("novel_name", "genre", "total_chapters_written")

_lg_client = None  # 模块级懒缓存：langgraph 平台 SDK 客户端（自调用本机平台 API）


def _get_lg_client():
    global _lg_client
    if _lg_client is None:
        # 惰性 import：langgraph_sdk 是平台依赖，dev 运行时必装
        from langgraph_sdk import get_client

        # 自调用同进程的平台 API；端口与 dev-backend.sh 一致（.env.local 的 LANGGRAPH_PORT）
        port = os.environ.get("LANGGRAPH_PORT", "28123")
        _lg_client = get_client(url=f"http://127.0.0.1:{port}")
    return _lg_client


async def get_novels_summary(request: Request) -> JSONResponse:
    """小说（thread）列表摘要：与 /threads/search 同形状，但 values 仅含摘要白名单字段。

    query: limit=<最多返回数，默认 200>
    resp:  [{ thread_id, status, created_at, updated_at, metadata,
             values: {白名单字段}, pending_resume: bool }, ...]

    pending_resume 语义：thread 处于 status=interrupted，且平台去归一后的 interrupts dict
    为空（即：不是真正的 human-in-the-loop 中断，而是上一次 run 未正常收尾，checkpoint 里
    还有 pending task 但没有活跃 run 在推）。前端据此在列表卡片渲染「▶」按钮，一键继续。
    典型触发场景：langgraph dev 服务重启、后端进程被 kill、网络断开导致 run 挂起。
    """
    try:
        limit = int(request.query_params.get("limit", "200"))
    except ValueError:
        limit = 200

    try:
        threads = await _get_lg_client().threads.search(limit=limit)
    except Exception as e:  # 自调用失败时回清晰错误，前端 useThreads 会捕获展示
        return JSONResponse({"error": f"threads.search failed: {e}"}, status_code=502)

    out = []
    for t in threads:
        values = t.get("values") or {}
        # 只挑白名单标量；total_chapters_written 缺省安全取 0（全新未运行的 thread）
        summary = {k: values.get(k) for k in _SUMMARY_VALUE_FIELDS}
        summary["total_chapters_written"] = values.get("total_chapters_written", 0)
        # pending_resume：status=interrupted 但 interrupts dict 为空 → 无真中断，仅 pending 卡住。
        # interrupts 平台返回 dict（按 task_id 键控）；empty 检测涵盖 None / {} / []。
        interrupts = t.get("interrupts")
        has_real_interrupt = bool(interrupts) if interrupts is not None else False
        pending_resume = t.get("status") == "interrupted" and not has_real_interrupt
        out.append(
            {
                "thread_id": t["thread_id"],
                "status": t.get("status"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
                "metadata": t.get("metadata") or {},
                "values": summary,
                "pending_resume": pending_resume,
            }
        )
    return JSONResponse(out)


# ── 应用组装 ─────────────────────────────────────────────────────────────────────
# 前端直连 langgraph dev（跨域），写接口（PUT）会触发预检，故挂 CORS 中间件放行。
routes = [
    Route("/prompt-overrides", get_prompt_overrides, methods=["GET"]),
    Route("/prompt-overrides", put_prompt_overrides, methods=["PUT"]),
    # 小说列表轻量摘要（替代前端对 /threads/search 的全量轮询）
    Route("/novels/summary", get_novels_summary, methods=["GET"]),
    # 不挂 html 索引：仅按文件名访问，避免暴露所有小说的文件清单
    Mount("/output", StaticFiles(directory=_output_dir), name="output"),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(routes=routes, middleware=middleware)
