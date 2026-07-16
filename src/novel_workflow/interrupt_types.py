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
    # Phase -1：灵感脑爆（可选，入口分叉）
    # ============================================================
    BRAINSTORM_GATE = "brainstorm_gate"  # 入口门：进脑爆 / 直接填表
    BRAINSTORM_CHAT = "brainstorm_chat"  # 多轮聊天等待用户消息
    # 脑爆结束轮的完整版确认闸门：finalize 流式生成 markdown 完整版后停下，让用户确认「使用」或「返回聊天」
    BRAINSTORM_FINALIZE_CONFIRM = "brainstorm_finalize_confirm"
    # 脑爆结束后的整合 review：一次性 review + 编辑 4 个正式设定字段，取代原 4 个逐项 confirm
    BRAINSTORM_EXTRACT_REVIEW = "brainstorm_extract_review"
    # 以下 4 个 confirm 已被 BRAINSTORM_EXTRACT_REVIEW 合并接管；节点函数与枚举保留，图上不再挂，以便回滚
    BRAINSTORM_CORE_THEME_CONFIRM = "brainstorm_core_theme_confirm"  # 核心主题轻量确认（已合并到 EXTRACT_REVIEW）
    BRAINSTORM_WORLD_BUILDING_CONFIRM = "brainstorm_world_building_confirm"  # 世界观轻量确认（已合并到 EXTRACT_REVIEW）
    BRAINSTORM_POWER_SYSTEM_CONFIRM = "brainstorm_power_system_confirm"  # 力量体系轻量确认（已合并到 EXTRACT_REVIEW）
    BRAINSTORM_CORE_CONFLICTS_CONFIRM = "brainstorm_core_conflicts_confirm"  # 核心冲突轻量确认（已合并到 EXTRACT_REVIEW）

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

    # 人物动态（处境/动机/关系）已并入 CharacterCard，由 entity_discover 单腿更新——
    # 原 STATUS_* / RELATIONS_* 两组快照 gate 已删。

    # 伏笔台账快照
    FORESHADOWING_ENTRY_GATE = "foreshadowing_entry_gate"  # 伏笔更新入门
    FORESHADOWING_DIRECTION_INPUT = "foreshadowing_direction_input"  # 伏笔调整方向输入
    FORESHADOWING_REVIEW = "foreshadowing_review"  # 伏笔台账审核

    # 阶段固化数据快照
    PHASE_SUMMARY_ENTRY_GATE = "phase_summary_entry_gate"  # 阶段数据更新入门
    PHASE_SUMMARY_DIRECTION_INPUT = "phase_summary_direction_input"  # 阶段数据调整方向输入
    PHASE_SUMMARY_REVIEW = "phase_summary_review"  # 阶段固化数据审核

    # 章级 scene beats（章前节拍表，可跳步骤；插在 save_titles 之后、prepare_chapter 之前）
    SCENE_BEATS_ENTRY_GATE = "scene_beats_entry_gate"  # 是否为本章生成 scene beats
    SCENE_BEATS_DIRECTION_INPUT = "scene_beats_direction_input"  # scene beats 调整方向输入（预留）
    SCENE_BEATS_REVIEW = "scene_beats_review"  # scene beats 审核

    # 章前登场实体卡（EntityCard：人物/物品/装备/势力/地点，可跳步骤；插在 scene_beats 之后、prepare_chapter 之前）
    ENTITY_CARDS_ENTRY_GATE = "entity_cards_entry_gate"  # 是否为本章登场实体建卡
    ENTITY_CARDS_DIRECTION_INPUT = "entity_cards_direction_input"  # 调整方向输入（预留，ask_direction=False 不触发）
    ENTITY_CARDS_REVIEW = "entity_cards_review"  # 登场实体卡审核

    # 章末实体发现 + 动态更新（读已写正文补卡 + 更新装备状态/人物动机；插在 phase_step 之后）
    ENTITY_DISCOVER_ENTRY_GATE = "entity_discover_entry_gate"  # 是否发现本章新实体 / 更新卡库
    ENTITY_DISCOVER_DIRECTION_INPUT = "entity_discover_direction_input"  # 调整方向输入（预留）
    ENTITY_DISCOVER_REVIEW = "entity_discover_review"  # 实体发现/更新审核

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
    # 伏笔台账精简流程
    # ============================================================
    FORESHADOW_PRUNE_ASK = "foreshadow_prune_ask"  # 询问是否精简
    FORESHADOW_PRUNE_CONFIRM = "foreshadow_prune_confirm"  # 确认精简结果

    # ============================================================
    # 分卷（Volume）相关中断
    # ============================================================
    # 分卷边界穿越闸门：chapter_plan 前瞻窗口若穿越某卷 target_min/target_max 时，
    # interrupt 让用户三选一（继续本卷 / 在第 X 章收卷 / 延长 target_max）。
    VOLUME_BOUNDARY_GATE = "volume_boundary_gate"

    # ============================================================
    # 其他中断
    # ============================================================
    ASK_CONTINUE = "ask_continue"  # 是否继续写下一批
    CONSISTENCY_GATE = "consistency_gate"  # 设定一致性总审闸门（save_config 冻结前，跨设定终审）
    CONSISTENCY_DIFF = "consistency_diff"  # 一致性总审 · AI 修订改前/改后 diff 审核闸门


# ============================================================
# review_type → InterruptType 映射
# ============================================================
# review_subgraph / edit_step_subgraph 中的 human_review 被 8+ 个业务场景复用，
# 具体身份由 prepare_fn 写入 state.review_type 携带（上游业务传参）。
# human_review 据此反查精确的 InterruptType，写入 payload 的 type 字段，
# 让前端无需猜测即可定位表单与业务上下文。
_REVIEW_TYPE_TO_INTERRUPT_TYPE: dict[str, InterruptType] = {
    "foreshadowing": InterruptType.FORESHADOWING_REVIEW,
    "phase_summary": InterruptType.PHASE_SUMMARY_REVIEW,
    "chapter": InterruptType.REVIEW_CHAPTER,
    "scene_beats": InterruptType.SCENE_BEATS_REVIEW,
    # 章前登场实体卡走专属 InterruptType
    "entity_cards": InterruptType.ENTITY_CARDS_REVIEW,
    # 章末实体发现/更新走专属 InterruptType
    "entity_discover": InterruptType.ENTITY_DISCOVER_REVIEW,
    # 分卷规划走通用 review 表单（前端 VolumesReviewForm 按 review_type 分派渲染）
    "volumes": InterruptType.REVIEW_GENERIC,
    # 以下 review_type 共用通用审核表单，归入 REVIEW_GENERIC：
    #   foundation / core_theme / world_building / core_conflicts /
    #   overall_outline / character_cards（Phase-1 结构化卡司）/ titles / arc_outline
}


def review_type_to_interrupt_type(review_type: str) -> InterruptType:
    """review_type → 精确 InterruptType，供 human_review 自报身份。

    未显式映射的 review_type（基础设定类、标题、弧线大纲等）统一归入
    REVIEW_GENERIC，复用通用审核表单。
    """
    return _REVIEW_TYPE_TO_INTERRUPT_TYPE.get(review_type, InterruptType.REVIEW_GENERIC)
