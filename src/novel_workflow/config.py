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


def _read_str_set(env_name: str, default: set[str]) -> set[str]:
    """读环境变量为逗号分隔的字符串集合;未设置/全空时落回 default。空白项与首尾空格自动剔除。

    覆盖语义(非追加):一旦设置该 env,即完全替换 default——需列全想保留的项。
    """
    raw = os.environ.get(env_name)
    if raw is None or raw.strip() == "":
        return set(default)
    return {item.strip() for item in raw.split(",") if item.strip()}


# ── 分卷章数松护栏（滚动生成卷时钳制 LLM 产出的本卷章数）─────────────────────────
#
# 长篇连载卷长由 LLM 内容驱动（不同卷承载内容大小不同），但需一道松护栏防跑偏：
# save_volumes 把 LLM 产出的「本卷章数」clamp 到 [MIN, MAX] 并打 warning；人类可在
# review_volumes 抽屉里突破此范围（LLM 夹、人可破）。默认 15~50 章。
VOLUME_MIN_CHAPTERS: int = _read_positive_int("NOVEL_VOLUME_MIN_CHAPTERS", 15)
VOLUME_MAX_CHAPTERS: int = _read_positive_int("NOVEL_VOLUME_MAX_CHAPTERS", 50)
if VOLUME_MIN_CHAPTERS > VOLUME_MAX_CHAPTERS:
    print(
        f"[config] NOVEL_VOLUME_MIN_CHAPTERS={VOLUME_MIN_CHAPTERS} 大于 "
        f"NOVEL_VOLUME_MAX_CHAPTERS={VOLUME_MAX_CHAPTERS},二者对调"
    )
    VOLUME_MIN_CHAPTERS, VOLUME_MAX_CHAPTERS = VOLUME_MAX_CHAPTERS, VOLUME_MIN_CHAPTERS


# ── 卷前瞻队列深度 ────────────────────────────────────────────────────────────
#
# 每次规划「1 个激活卷（要立即展开）+ N 个前瞻草稿卷」，N = 本值。草稿卷只出方向骨架
# （title/summary/setup_for_next）、不锁章号（chapter_start=planned_end=0, status=planning），
# 给当前卷规划提供中期地图；轮到时才由 save_volumes 权威锁章号转正激活。默认 2（一次输出 3 卷）。
VOLUME_LOOKAHEAD: int = _read_positive_int("NOVEL_VOLUME_LOOKAHEAD", 2)


# ── 章末精简(伏笔台账 + 实体卡库)节流步长 ─────────────────────────────────────
#
# 精简 = LLM 分析整库 + 人工/自动勾选删库。默认每章都触发,代价高(每章一次 LLM 调用
# + 破坏性删库);自动模式下更是每章无脑跑。此步长把它节流为「每 N 章执行一次」:仅当
# 刚写完的章号(total_chapters_written)是 N 的整数倍时才进入精简,否则 ask 节点直接跳过
# ——不弹中断、不调 LLM。伏笔台账与实体卡库共用此步长(用户拍板:一个步长同管两者)。
#   N=3(默认)→ 第 3/6/9… 章末各精简一次
#   N=1      → 每章都精简(等价旧行为)
# 节流在后端 ask 节点统一生效:后端不感知前端自动模式,故手动/自动模式行为一致。
PRUNE_STRIDE: int = _read_positive_int("NOVEL_PRUNE_STRIDE", 3)


def should_prune_at_chapter(chapter_number: int) -> bool:
    """判断刚写完第 chapter_number 章后,是否到达精简节流点。

    chapter_number 传 state.total_chapters_written(精简 ask 运行时已是刚写完的章号)。
    <=0(尚未写任何章)一律不精简;否则按 PRUNE_STRIDE 整除判定。
    """
    if chapter_number <= 0:
        return False
    return chapter_number % PRUNE_STRIDE == 0


# ── 关闭 LLM 自审的 review_type 集合 ─────────────────────────────────────────
#
# 写作循环里的「结构化数据维护」类不需要创作级自审,直接跳过——省下自审调用本身,以及
# 自审挑刺触发的连锁重写(如 entity_cards 常跑 2-3 轮)。保留自审的是创作/骨架类:
# chapter 正文、chapter_plan 长线大纲、arc_outline 弧线大纲,以及开写前的设定固化类。
# 逻辑在 subgraph.llm_self_review 唯一开关点消费本集合。
#
# 经 env 逗号分隔覆盖(覆盖语义,非追加):
#   NOVEL_SELF_REVIEW_DISABLED_TYPES=titles,scene_beats  → 只关这两类
#   留空/未设 → 用下方默认集合。
_DEFAULT_SELF_REVIEW_DISABLED_TYPES: set[str] = {
    "titles",
    "scene_beats",
    "entity_cards",
    "foreshadowing",
    "phase_summary",
    "entity_discover",
}
SELF_REVIEW_DISABLED_TYPES: frozenset[str] = frozenset(
    _read_str_set("NOVEL_SELF_REVIEW_DISABLED_TYPES", _DEFAULT_SELF_REVIEW_DISABLED_TYPES)
)

