"""Interrupt 类型枚举 — 前后端契约式设计，避免脆弱的字符串匹配。

设计原则：
1. 所有 interrupt() 调用必须显式指定 type 字段
2. type 字段值必须与本枚举一致
3. 前端直接根据 type 字段判断表单类型，避免 message.includes
"""

from enum import Enum


class InterruptType(str, Enum):
    """中断类型枚举，作为前后端 API 契约的一部分。"""

    # ============================================================
    # 用户输入阶段（新建小说）
    # ============================================================
    USER_INPUTS = "user_inputs"  # 基础参数输入
    USER_INPUTS_ERROR = "user_inputs_error"  # 输入错误重试

    # ============================================================
    # chapter_edit_subgraph 的 5 个串行步骤
    #（每个步骤都包含 entry_gate + direction_input + human_review）
    # ============================================================

    # 弧线大纲步骤
    ARC_ENTRY_GATE = "arc_entry_gate"  # 弧线调整入门（跳过/执行）
    ARC_DIRECTION_INPUT = "arc_direction_input"  # 弧线调整方向输入
    ARC_CONFIRM = "arc_confirm"  # 弧线 AI 生成结果确认
    ARC_CONFIRM_ERROR = "arc_confirm_error"  # 弧线生成失败，手动输入

    # 人物动态状态快照
    STATUS_ENTRY_GATE = "status_entry_gate"  # 人物状态更新入门
    STATUS_DIRECTION_INPUT = "status_direction_input"  # 状态调整方向输入
    STATUS_REVIEW = "status_review"  # 人物动态状态审核

    # 人物关系/势力格局快照
    RELATIONS_ENTRY_GATE = "relations_entry_gate"  # 关系格局更新入门
    RELATIONS_DIRECTION_INPUT = "relations_direction_input"  # 关系调整方向输入
    RELATIONS_REVIEW = "relations_review"  # 人物关系审核

    # 伏笔台账快照
    FORESHADOWING_ENTRY_GATE = "foreshadowing_entry_gate"  # 伏笔更新入门
    FORESHADOWING_DIRECTION_INPUT = "foreshadowing_direction_input"  # 伏笔调整方向输入
    FORESHADOWING_REVIEW = "foreshadowing_review"  # 伏笔台账审核

    # 阶段固化数据快照
    PHASE_SUMMARY_ENTRY_GATE = "phase_summary_entry_gate"  # 阶段数据更新入门
    PHASE_SUMMARY_DIRECTION_INPUT = "phase_summary_direction_input"  # 阶段数据调整方向输入
    PHASE_SUMMARY_REVIEW = "phase_summary_review"  # 阶段固化数据审核

    # ============================================================
    # arc_edit_subgraph 独立使用的标题确认
    # ============================================================
    ARC_TITLES_CONFIRM = "arc_titles_confirm"  # 章节标题重生成确认

    # ============================================================
    # 通用 review_subgraph（所有 generate → review 流程共用）
    # ============================================================
    REVIEW_GENERIC = "review_generic"  # 通用审核（用于基础设定、核心主题等）
    REVIEW_CHAPTER = "review_chapter"  # 章节正文审核

    # ============================================================
    # 其他中断
    # ============================================================
    ASK_CONTINUE = "ask_continue"  # 是否继续写下一批


# ============================================================
# review_type → InterruptType 映射
# ============================================================
# review_subgraph / edit_step_subgraph 中的 human_review 被 8+ 个业务场景复用，
# 具体身份由 prepare_fn 写入 state.review_type 携带（上游业务传参）。
# human_review 据此反查精确的 InterruptType，写入 payload 的 type 字段，
# 让前端无需猜测即可定位表单与业务上下文。
_REVIEW_TYPE_TO_INTERRUPT_TYPE: dict[str, InterruptType] = {
    "character_status": InterruptType.STATUS_REVIEW,
    "character_relations": InterruptType.RELATIONS_REVIEW,
    "foreshadowing": InterruptType.FORESHADOWING_REVIEW,
    "phase_summary": InterruptType.PHASE_SUMMARY_REVIEW,
    "chapter": InterruptType.REVIEW_CHAPTER,
    # 以下 review_type 共用通用审核表单，归入 REVIEW_GENERIC：
    #   foundation / core_theme / world_building / core_conflicts /
    #   overall_outline / character_profiles / titles / arc_outline
}


def review_type_to_interrupt_type(review_type: str) -> InterruptType:
    """review_type → 精确 InterruptType，供 human_review 自报身份。

    未显式映射的 review_type（基础设定类、标题、弧线大纲等）统一归入
    REVIEW_GENERIC，复用通用审核表单。
    """
    return _REVIEW_TYPE_TO_INTERRUPT_TYPE.get(review_type, InterruptType.REVIEW_GENERIC)
