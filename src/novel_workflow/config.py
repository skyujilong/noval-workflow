"""Global configuration constants derived from environment variables."""

from __future__ import annotations

import os

BATCH_SIZE: int = int(os.environ.get("NOVEL_BATCH_SIZE", "5"))

# 设定一致性总审的重审轮数上限（audit → gate → 复审 的循环安全阀）。
# 达此轮数后强制放行冻结，杜绝反复重审卡死。默认 3；可经 env 调整。
MAX_AUDIT_ROUNDS: int = int(os.environ.get("CONSISTENCY_MAX_AUDIT_ROUNDS", "3"))

# Context window split: how many of the most-recent chapters to include as full
# text vs. summary-only.  Tuned for token efficiency without breaking coherence.
#   FULL_COUNT=1  → 只保留紧邻上一章的完整原文，保证情节/对话/伏笔精准承接
#   SUMMARY_COUNT=2  → 往前两章只用摘要，知道关键剧情节点即可
#   总计：前3章有效上下文（比之前减少1章完整内容，约降 4k~7k token）
FULL_COUNT: int = 1
SUMMARY_COUNT: int = 2
