"""Novel creation workflow powered by LangGraph."""

from noval_workflow.logging_setup import setup_logging

# 包被任一入口（langgraph graph.py / http_app.py）import 时即配置日志：模块区分 + 落盘。
# 放在包 __init__ 是唯一能覆盖两个入口的早期钩子（无独立 main()）；setup_logging 幂等。
setup_logging()
