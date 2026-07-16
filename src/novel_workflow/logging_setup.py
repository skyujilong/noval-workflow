"""集中式日志配置：模块区分 + 落盘（graph / http_app 两个入口共用）。

痛点：langgraph 平台默认只把 root logger 打到控制台、**不落盘**，各节点日志混在一起、
跑完就散。本模块给 `noval_workflow` 包 logger 统一挂两个 handler：
- 控制台（保留边跑边看）
- 轮转文件（落盘，默认 ./logs/noval_workflow.log，可用 env 覆盖）

两个 handler 的 formatter 都带 `%(name)s`——即各模块 `getLogger(__name__)` 的
`noval_workflow.xxx` 全路径，天然按模块区分。设 `propagate=False`，避免本包日志既走
这里的 handler、又冒泡到 root 被 langgraph 再打印一遍（控制台重复行）。

配置对象是**包级 logger**（`noval_workflow`）而非 root：只收敛「咱们自己的日志」，
不接管 uvicorn / langgraph_api 的输出，避免干扰平台既有日志。

env 覆盖：
- NOVEL_LOG_LEVEL  日志级别（默认 INFO）
- NOVEL_LOG_DIR    落盘目录（默认 ./logs，相对 langgraph dev 启动 cwd = 项目根）
- NOVEL_LOG_FILE   文件名（默认 noval_workflow.log）
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PKG_LOGGER = "noval_workflow"
# LLM 调用组成落盘用的专用 logger：独立 jsonl 文件，一次调用一行结构化记录，
# 便于后期用脚本统计「哪个环节多少 token、system context 各 section 占多少」。
_LLM_CALLS_LOGGER = "noval_workflow.llm_calls"
# 幂等：langgraph 可能多次 import 触发本模块，只配置一次，避免 handler 叠加导致每行重复 N 遍
_configured = False


def _setup_llm_calls_logger(log_dir: Path) -> None:
    """给 LLM 调用画像配一个只写 jsonl 的独立 logger（不混进主 log、不打控制台）。

    每行是一条完整 JSON（环节 label + 各 section 长度/预览 + token 用量 + 耗时），
    formatter 只输出 message 本体，propagate=False 避免冒泡到包 logger 再打印一遍。
    """
    logger = logging.getLogger(_LLM_CALLS_LOGGER)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(
        log_dir / "llm_calls.jsonl",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def setup_logging() -> None:
    """配置 `noval_workflow` 包 logger（控制台 + 落盘），幂等，供包 __init__ 调用。"""
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.environ.get("NOVEL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(_PKG_LOGGER)
    logger.setLevel(level)
    # 本包日志只走下面的 handler，不再冒泡到 root（否则 langgraph 的 root 控制台 handler 会重复打印）
    logger.propagate = False

    # 统一格式：时间 | 级别 | 模块(__name__ 全路径) | 消息
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    # 落盘：轮转文件，单个 10MB、留 5 个备份
    log_dir = Path(os.environ.get("NOVEL_LOG_DIR", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / os.environ.get("NOVEL_LOG_FILE", "noval_workflow.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # LLM 调用画像单独落一个 jsonl，供后期分析输入 token 组成/精简空间
    _setup_llm_calls_logger(log_dir)

    logger.info("日志已初始化：level=%s 落盘=%s", level_name, log_file.resolve())
