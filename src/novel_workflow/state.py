import operator
from dataclasses import dataclass, field
from typing import Annotated


@dataclass
class ReviewSubState:
    genre: str = ""             # 小说类型（桥接字段：按题材加载提示词包；由父图 NovelState.genre 自动映射）
    system_context: str = ""    # 系统提示词（来自 build_foundation_context）
    task_prompt: str = ""       # 本次生成任务的具体指令（由父图 prepare 节点写入）
    current_draft: str = ""     # 当前迭代中的草稿内容
    review_feedback: str = ""   # LLM 或人工反馈（空字符串 = 无问题 / 已通过）
    approved: bool = False      # 人工审核通过后置为 True
    review_type: str = "foundation"  # 选择审稿提示词："foundation"|"titles"|"chapter"|"arc_outline"|...
    review_history: list = field(default_factory=list)
    # list[dict]，每条格式：{"role": "human"|"ai", "content": str}
    # 由 generate() 管理；按 _HISTORY_MAX_ROUNDS 上限滚动裁剪（每轮 2 条消息）
    llm_review_count: int = 0
    # LLM 自审累计轮数；达到上限后强制转人工，human_review 节点重置为 0
    llm_review_max: int = 3
    # LLM 自审轮数上限（可由子图工厂覆写）


@dataclass
class NovelState:
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
    review_type: str = "foundation" # 审稿类型，决定使用哪条 review prompt
    llm_review_count: int = 0       # LLM 自审累计轮数（子图桥接字段）

    # ── Phase 1：小说基础设定（每项审核通过后保存）────────────────────────────────
    core_theme: str = ""            # 核心主题与立意
    world_building: str = ""        # 世界观设定
    core_conflicts: str = ""        # 核心冲突设计
    overall_outline: str = ""       # 整体大纲与结局
    character_profiles: str = ""    # 人物档案（主角 + 主要配角 + 反派）

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
