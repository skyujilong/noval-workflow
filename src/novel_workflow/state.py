import operator
from dataclasses import dataclass, field
from typing import Annotated


@dataclass
class ReviewSubState:
    novel_name: str = ""        # 小说名称（桥接字段：按小说加载提示词覆盖；由父图 NovelState.novel_name 自动映射）
    genre: str = ""             # 小说类型（桥接字段：按题材加载提示词包；由父图 NovelState.genre 自动映射）
    system_context: str = ""    # 系统提示词（来自 build_foundation_context）
    task_prompt: str = ""       # 本次生成任务的具体指令（由父图 prepare 节点写入）
    current_draft: str = ""     # 当前迭代中的草稿内容
    review_feedback: str = ""   # LLM 或人工反馈（空字符串 = 无问题 / 已通过）
    approved: bool = False      # 人工审核通过后置为 True
    review_type: str = "foundation"  # 初始哨兵值；prepare 节点必覆盖为已登记类型（core_theme|titles|chapter|arc_outline|…），未覆盖即进 review 会 fail-fast
    review_history: list = field(default_factory=list)
    # list[dict]，每条格式：{"role": "human"|"ai", "content": str}
    # 由 generate() 管理；按 _HISTORY_MAX_ROUNDS 上限滚动裁剪（每轮 2 条消息）
    llm_review_count: int = 0
    # LLM 自审累计轮数；达到上限后强制转人工，human_review 节点重置为 0
    llm_review_max: int = 3
    # LLM 自审轮数上限（可由子图工厂覆写）
    thinking_override: str | None = None
    # 人工审核打回时用户对「深度思考」的显式选择："enabled"|"disabled"|None。
    # None = 不覆盖，generate 按 review_type 走默认策略（创作类开思考 / 快照类关思考）。
    # 仅在子图内 human_review→generate 循环里流转，不桥接到 NovelState，故每次进子图自动归零。
    human_feedback: str = ""
    # 最近一次人工审核打回的原始意见（持久保留）。与瞬时的 review_feedback 区分：
    #   - review_feedback 是「本轮待处理反馈」通道，被 generate 消费后立即清空为 ""；
    #   - human_feedback 在整个 human_review→generate→llm_self_review 循环里持续保留，
    #     供 llm_self_review 核对人工意见是否已落实（generate 清空 review_feedback 后，
    #     自审若仍读 review_feedback 就会拿到空串 → 人工意见丢失，故必须单独存一份）。
    # 由 human_review 写入（打回时置为原始意见，通过时重置为 ""）；不桥接到 NovelState，每次进子图自动归零。


@dataclass
class NovelState:
    # ── Phase -1：灵感脑爆（可选，入口分叉）──────────────────────────────────────
    brainstorm_history: list = field(default_factory=list)
    # 脑爆多轮对话历史，格式 [{"role": "human"|"ai", "content": str}]。
    # 覆盖语义（节点每次返回完整新 list）——切勿加 operator.add，否则压缩无法移除旧条目。
    brainstorm_summary: str = ""    # 早期对话轮次的 LLM 压缩概要（滑出保留窗口的部分并入此处）
    brainstorm_done: bool = False   # 用户已结束脑爆（brainstorm_chat 路由用）
    from_brainstorm: bool = False   # 入口分叉标志：True=经脑爆而来。破除 collect 跳过短路 + collect 后路由。全程不重置。

    # ── Phase 0：用户输入 ────────────────────────────────────────────────────────
    novel_name: str = ""            # 小说名称
    genre: str = ""                 # 小说类型（玄幻/都市/科幻等）
    writing_style: str = ""         # 写作风格（硬核爽文/细腻文学等）
    target_audience: str = ""       # 目标读者群体
    core_tone: str = ""             # 核心基调（热血/悬疑/温情等）
    chapter_word_count: str = ""    # 每章目标字数
    total_word_count: str = ""      # 全书总字数目标

    # ── 子图桥接字段（字段名与 ReviewSubState 完全一致，供 LangGraph 自动映射）────
    system_context: str = ""        # 当前节点的系统提示词（prepare 节点写入，子图消费）
    task_prompt: str = ""           # 当前节点的生成任务指令（prepare 节点写入，子图消费）
    current_draft: str = ""         # 子图审核完成后的最终草稿（由子图写回父图）
    review_feedback: str = ""       # 审核反馈（LLM 或人工；空 = 通过）
    approved: bool = False          # 审核是否通过
    review_type: str = "foundation" # 初始哨兵值；prepare 节点必覆盖为已登记 review 类型（未覆盖进 review 即 fail-fast）
    llm_review_count: int = 0       # LLM 自审累计轮数（子图桥接字段）

    # ── Phase 1：小说基础设定（每项审核通过后保存）────────────────────────────────
    core_theme: str = ""            # 核心主题与立意
    world_building: str = ""        # 世界观设定
    core_conflicts: str = ""        # 核心冲突设计
    overall_outline: str = ""       # 整体大纲与结局
    character_profiles: str = ""    # 人物档案（主角 + 主要配角 + 反派）

    # ── 设定一致性总审（save_config 冻结前的跨设定闸门；transient，覆盖语义，无 reducer）──
    # 每次进入 audit_consistency / consistency_gate 都被节点主动覆盖，无残留风险；
    # 不进 reset_review_fields()（那是 review_subgraph 桥接字段清理，本闸门不走子图）。
    consistency_report: str = ""      # 最近一次审计报告全文（audit 写，gate 展示）："无问题" 或问题清单
    consistency_pass: bool = False    # 审计判定通过（路由 / 前端提示用）
    consistency_audit_count: int = 0  # 已审计轮数，达 _MAX_AUDIT_ROUNDS 强制放行、防死循环

    # ── Phase 2：章节写作追踪 ───────────────────────────────────────────────────
    current_batch_titles: list[str] = field(default_factory=list)
    # 当前批次的章节标题列表（每批 BATCH_SIZE 个，每批开始时重置）

    # LangGraph >= 1.2 对 dataclass 支持 Annotated reducer；operator.add 实现追加语义
    all_chapter_titles: Annotated[list[str], operator.add] = field(default_factory=list)
    # 全书已生成的所有章节标题（跨批次累积，索引 i 对应第 i+1 章）

    all_chapter_summaries: Annotated[list[str], operator.add] = field(default_factory=list)
    # 全书已生成的所有章节摘要（与 all_chapter_titles 索引对齐，缺失章节存空字符串）

    current_chapter_index: int = 0  # 当前批次内的写作进度（0 = 第 1 章未写；每批开始时重置为 0）
    total_chapters_written: int = 0 # 全书已完成章节总数（跨批次累积）
    continue_writing: bool = True   # ask_continue 节点的用户决策：True = 继续下一批

    # ── Phase 2.5：批次小号大纲（arc outline）────────────────────────────────────
    current_arc_outline: str = ""
    # 本批章节的故事弧线大纲（每批开始时由 save_arc_outline 覆盖写入，直接注入 system_context）

    # ── Phase 2.5：动态状态库（每次覆盖写入最新快照）────────────────────────────
    character_status: str = ""
    # 人物动态状态（主角 + 主要配角的当前位置/情绪/目标/处境）

    character_relations: str = ""
    # 人物关系/势力格局（各方关系变化 + 势力强弱对比）

    foreshadowing: dict = field(default_factory=dict)
    # 伏笔台账（结构化 JSON：{"pending": [...], "collected": [...]}）

    phase_summary: str = ""
    # 阶段固化数据（主角等级/装备/技能/资源等硬性数值，后续创作必须遵守）



def reset_review_fields() -> dict:
    """Return a dict that clears the shared review bridge fields."""
    return {"current_draft": "", "review_feedback": "", "approved": False, "review_history": [], "llm_review_count": 0, "llm_review_max": 3}
