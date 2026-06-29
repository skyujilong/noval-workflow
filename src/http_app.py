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


# ── 应用组装 ─────────────────────────────────────────────────────────────────────
# 前端直连 langgraph dev（跨域），写接口（PUT）会触发预检，故挂 CORS 中间件放行。
routes = [
    Route("/prompt-overrides", get_prompt_overrides, methods=["GET"]),
    Route("/prompt-overrides", put_prompt_overrides, methods=["PUT"]),
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
