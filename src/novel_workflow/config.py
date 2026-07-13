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


# ── 章节规划(chapter_plan)远端锚点层 ──────────────────────────────────────────
#
# 在整书 overall_outline 与批级 arc_outline 之间新增的一层「中景大纲」，滚动窗口
# 向前规划 N 章的 4 字段 JSON 条目(chapter/purpose/key_turn/ending_hook)。已写完
# 的条目永久锁定；每写完 STRIDE 章触发一次重规划，把未写部分覆盖为新版本。
#
# 用途:给 arc_outline 每批 BATCH_SIZE 章提供「远端锚点」,减少 drift。
#
# 环境变量读入 + fail-soft clamp:
#   * WINDOW 保底 >= BATCH_SIZE(否则一批弧线大纲会超出远端锚点范围)
#   * STRIDE 保底 <= WINDOW,且建议为 BATCH_SIZE 的整数倍以对齐批边界
#   * ENABLED=false 时全链路跳过,主链等价旧行为(v1 保底开关)

_DEFAULT_CHAPTER_PLAN_WINDOW: int = 40
_DEFAULT_CHAPTER_PLAN_STRIDE: int = 10


def _read_positive_int(env_name: str, default: int) -> int:
    """读环境变量为正整数;非法(非数字/<=0)时 warning + 落回默认值。"""
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"[config] {env_name}={raw!r} 无法解析为整数,回退默认值 {default}")
        return default
    if value <= 0:
        print(f"[config] {env_name}={value} 必须 > 0,回退默认值 {default}")
        return default
    return value


def _read_bool(env_name: str, default: bool) -> bool:
    """读环境变量为布尔;接受 true/false/1/0/yes/no(大小写不敏感),其他值 warning + 落回默认。"""
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    print(f"[config] {env_name}={raw!r} 不是合法布尔,回退默认值 {default}")
    return default


CHAPTER_PLAN_ENABLED: bool = _read_bool("NOVEL_CHAPTER_PLAN_ENABLED", True)

_raw_window = _read_positive_int("NOVEL_CHAPTER_PLAN_WINDOW", _DEFAULT_CHAPTER_PLAN_WINDOW)
if _raw_window < BATCH_SIZE:
    print(
        f"[config] NOVEL_CHAPTER_PLAN_WINDOW={_raw_window} 小于 BATCH_SIZE={BATCH_SIZE},"
        f"提升到 BATCH_SIZE"
    )
    _raw_window = BATCH_SIZE
CHAPTER_PLAN_WINDOW: int = _raw_window

_raw_stride = _read_positive_int("NOVEL_CHAPTER_PLAN_STRIDE", _DEFAULT_CHAPTER_PLAN_STRIDE)
if _raw_stride > CHAPTER_PLAN_WINDOW:
    print(
        f"[config] NOVEL_CHAPTER_PLAN_STRIDE={_raw_stride} 大于 WINDOW={CHAPTER_PLAN_WINDOW},"
        f"钳制到 WINDOW"
    )
    _raw_stride = CHAPTER_PLAN_WINDOW
CHAPTER_PLAN_STRIDE: int = _raw_stride

