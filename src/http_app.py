"""自定义 HTTP 路由：挂载 output 目录为静态文件服务，供前端阅读章节正文。

通过 langgraph.json 的 http.app 配置加载，与平台 API 同端口（默认 8123）合并、
无前缀。前端经 <API_URL>/output/<小说名>/chapters/*.txt 读取章节正文。

目录解析相对于 langgraph dev 的启动 cwd（项目根），默认 ./output；
可用 NOVEL_OUTPUT_DIR 环境变量覆盖（与 noval_workflow.context.get_output_dir 一致）。

注意：langgraph_api 运行时只安装了 starlette（无 fastapi），故此处用 Starlette。
"""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

# output 根目录：与 context.get_output_dir 保持同一来源
_output_dir = os.environ.get("NOVEL_OUTPUT_DIR", "./output")

# 挂载前确保目录存在：StaticFiles 构造时会校验 directory，缺失会抛 RuntimeError，
# 导致整个 langgraph dev 启动失败。./output 是工作流输出根目录，首启时尚未被创建，
# 这里无条件建空目录（exist_ok=True 幂等），不影响后续 save_chapter 等正常写入。
os.makedirs(_output_dir, exist_ok=True)

app = Starlette()
# 不挂 html 索引：仅按文件名访问，避免暴露所有小说的文件清单
app.mount("/output", StaticFiles(directory=_output_dir), name="output")
