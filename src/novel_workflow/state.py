import operator
from dataclasses import dataclass, field
from typing import Annotated


@dataclass
class ChapterPlanItem:
    """章节规划单条条目——中景大纲层的结构化章节条目。

    LangGraph checkpoint 序列化时 dataclass 自动转 dict，前端拿到的仍是标准 JSON；
    LLM 出的 JSON 数组由 save_chapter_plan 逐条 `ChapterPlanItem(**item)` 造实例，
    字段缺失/类型错时抛 TypeError，让审核循环重生成。

    intensity 档位（7 档，与 arc 层 6 档对齐但更细）：
      铺垫/缓冲/推进/小转折/大转折/爆发/回落
    老 state 快照反序列化时缺字段走默认值，不会炸。
    """

    chapter: int           # 全书章号（1-based）
    purpose: str           # 本章要完成的「活」/目标（≤40 字）
    key_turn: str          # 本章关键事件/看点（≤40 字，禁止用"无强转折"套话）
    ending_hook: str       # 章末钩子（≤30 字，必须是具体事件，禁止"XX出现"套路）
    intensity: str = ""    # 本章档位：铺垫/缓冲/推进/小转折/大转折/爆发/回落


@dataclass
class Volume:
    """整书分卷条目——横向大结构，位于 overall_outline 之下、chapter_plan 之上。

    弹性 range 语义（关键，与作者/LLM 直觉对齐）：
      - chapter_start 是本卷**起始章号**（1-based，锁定）
      - target_min / target_max 是本卷**章数**（数量，软约束），不是绝对章号
      - 卷内绝对章号窗口 = [chapter_start, chapter_start + target_max - 1]
      - actual_end 只有在 VOLUME_BOUNDARY_GATE 用户点「在此收卷」后才写入绝对章号，
        在此之前 = None（当前卷进行中）
      - 拼接规则：chapter_start[i+1] = chapter_start[i] + target_max[i]（前卷按上限占位；
        实际收卷 actual_end < 上限时可重算后续卷 chapter_start，Step 05 处理）

    章 → 卷映射由 volume_utils.volume_of_chapter(chapter_num, volumes) 提供：
      - 已收卷（actual_end != None）：chapter ∈ [chapter_start, actual_end]
      - 进行中卷（actual_end == None）：chapter >= chapter_start 且是最靠前的未收卷

    序列化/容错照抄 ChapterPlanItem：LangGraph checkpoint 序列化时 dataclass 自动转 dict；
    LLM 出的 JSON 由 save_volumes 逐条 `Volume(**item)` 造实例，字段缺失/类型错时抛
    TypeError 触发审核循环重生成。老 state 快照反序列化时缺字段走默认值。
    """
    index: int                     # 第几卷（1-based）
    title: str                     # 卷名，如「第一卷 · 少年入宗」
    summary: str = ""              # 本卷主线目标 + 情绪基调 + 收尾状态（≤80 字）
    setup_for_next: str = ""       # 卷尾要为下一卷埋的钩（≤60 字，最后一卷可空）
    chapter_start: int = 1         # 起始**章号**（1-based，硬锁定）
    target_min: int = 0            # 目标**章数**下限（数量，软约束）
    target_max: int = 0            # 目标**章数**上限（数量，软约束）
    actual_end: int | None = None  # 实际收卷**章号**，None = 仍在进行中
    status: str = "planning"       # planning | in_progress | closed


@dataclass
class EntityCard:
    """统一实体卡——人物/物品/装备/势力/地点的结构化「触发式档案卡」。

    与 character_profiles（叙事全档案 markdown）的分工：EntityCard 是写正文时按
    「本章登场名单」注入 chapter_prompt 的**紧凑防飘锚点**（外貌/口吻/装备状态等固定字段），
    character_profiles 是背景铺陈全档案。二者字段/用途不同，非双源。

    装备/物品的真源：本卡是装备/物品的唯一真源（phase_summary 不再存装备），status/owner
    随章由章末 entity_discover_step 更新。

    序列化/容错约定照抄 ChapterPlanItem：LangGraph checkpoint 序列化时 dataclass 自动转 dict；
    LLM 出的 JSON 由 _save_entity_cards 逐条 `EntityCard(**c)` 造实例，字段缺失/类型错时抛
    TypeError 触发审核循环重生成。type 条件字段（人物段/物品段）不适用时留空默认值，
    老 state 快照反序列化缺字段走默认值不炸。
    """

    name: str                          # 实体名（主键，name+aliases 归一化后查重去重）
    type: str                          # 人物 / 物品 / 装备 / 势力 / 地点
    aliases: list[str] = field(default_factory=list)  # 别称（参与归一化查重，防同一实体重复建卡）
    summary: str = ""                  # 一句话定位（≤30 字）
    first_appear_chapter: int = 0      # 首次登场章号（1-based）
    # ── 人物专属（type=人物 时填；appearance/speech_style 是防写飘关键字段）──
    appearance: str = ""               # 外貌锚点（≤40 字）
    speech_style: str = ""             # 说话风格/口吻/口头禅（≤30 字）
    personality: str = ""              # 性格
    motivation: str = ""               # 当前动机/目标（动态字段，章末可更新）
    relations: str = ""                # 与主角/他人关系
    abilities: str = ""                # 能力底牌（须落【力量体系】框架）
    # ── 物品/装备专属（type=物品/装备 时填）──
    owner: str = ""                    # 归属人（动态字段，章末可更新）
    effect: str = ""                   # 效果/能力
    status: str = ""                   # 当前状态：完好/损坏/消耗/遗失（动态字段，章末可更新）
    rank: str = ""                     # 品阶/等级（落力量体系）


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
    # 脑爆产物 review 分支标志：True=用户在 review 抽屉里选「保存并推进」；False=选「返回脑爆继续修改」。
    # 只在 brainstorm_extract_review 节点内写；供 route_after_extract_review 决定去 collect_user_inputs 还是回 brainstorm_chat。
    brainstorm_review_advance: bool = False
    from_brainstorm: bool = False   # 入口分叉标志：True=经脑爆而来。破除 collect 跳过短路 + collect 后路由。全程不重置。

    # ── Phase -1.5：脑爆结束轮的"完整版 markdown + 用户确认"闸门 ────────────────
    # v2 保真度改造：brainstorm_finalize 让 LLM 流式输出「用户已认可的完整版」markdown（含
    # `# 核心主题 / # 世界观 / # 力量体系 / # 核心冲突` 一级标题分节），写入 finalize_markdown
    # 并追加进 brainstorm_history 的末条 AI 气泡——用户能在聊天页亲眼看到即将变成 review 内容的
    # 那份原文。brainstorm_finalize_confirm 拦一道 interrupt：
    #   - action=use → 纯 python 按 `# 标题` 正则切分 → 覆盖 4 个正式设定字段（绝无二次 LLM 改写）
    #   - action=back_to_chat → 剥掉 history 末条 finalize markdown + 复位 done + 清空这里的字段
    # 切不到的字段名累积到 finalize_missing_fields，供 brainstorm_extract_review 面板对应字段头部
    # 挂黄色警告条提示用户手填。
    finalize_markdown: str = ""            # 完整版 markdown 原文（供 confirm 闸门与 back_to_chat 剥离比对）
    finalize_missing_fields: list = field(default_factory=list)  # 切分不到的字段名子集（core_theme/world_building/power_system/core_conflicts）

    # ── Phase 0：用户输入 ────────────────────────────────────────────────────────
    novel_name: str = ""            # 小说名称
    genre: str = ""                 # 小说类型（玄幻/都市/科幻等）
    writing_style: str = ""         # 写作风格（硬核爽文/细腻文学等）
    target_audience: str = ""       # 目标读者群体
    core_tone: str = ""             # 核心基调（热血/悬疑/温情等）
    chapter_word_count: str = ""    # 每章目标字数
    total_word_count: str = ""      # 全书总字数目标

    # 作品是否包含独立【力量体系】——从题材默认建议（GenreFlavor.has_power_system）初始化，
    # 脑爆 review 抽屉里用户可覆盖。三个消费点统一读它（route_after_world_building /
    # brainstorm_finalize 抽后剔除 / brainstorm_extract_review payload），题材属性降级为默认值来源。
    # 直接填表路径由 collect_user_inputs 按题材默认写入；脑爆路径由 brainstorm_finalize 初始化 → review 抽屉可覆盖。
    has_power_system: bool = False

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
    power_system: str = ""          # 力量体系（修炼境界/科技/异能/社会竞争等，视题材而定；依赖世界观、喂给冲突/大纲/人物）
    core_conflicts: str = ""        # 核心冲突设计
    overall_outline: str = ""       # 整体大纲与结局
    character_profiles: str = ""    # 人物档案（主角 + 主要配角 + 反派）

    # ── Phase 1.5：分卷规划（Volumes，横向大结构中间层）─────────────────────────
    # 位于 overall_outline 之下、chapter_plan 之上。由 prepare_volumes 从 overall_outline
    # 抽取结构化 Volume 列表（默认 4 卷），走 review_volumes 人审后写入。弹性 range 语义
    # （详见 Volume dataclass 注释）：卷起点锁定，卷终点用 target_min/target_max 章数软约束
    # 表达，实际章数由 VOLUME_BOUNDARY_GATE（Step 05）根据剧情动态调整。
    # 覆盖语义：save_volumes 全量覆盖返回；不使用 operator.add（用户可能删卷/合并卷）。
    volumes: list[Volume] = field(default_factory=list)

    # ── 设定一致性总审（save_config 冻结前的跨设定闸门；transient，覆盖语义，无 reducer）──
    # 每次进入 audit_consistency / consistency_gate 都被节点主动覆盖，无残留风险；
    # 不进 reset_review_fields()（那是 review_subgraph 桥接字段清理，本闸门不走子图）。
    consistency_report: str = ""      # 最近一次审计报告全文（audit 写，gate 展示）："无问题" 或问题清单
    consistency_pass: bool = False    # 审计判定通过（路由 / 前端提示用）
    consistency_audit_count: int = 0  # 已审计轮数，达 _MAX_AUDIT_ROUNDS 强制放行、防死循环
    consistency_revisions: list = field(default_factory=list)
    # AI 修订提案：[{"field","label","before","after","reason"}]；diff_gate 展示，应用/放弃后清空
    consistency_action: str = ""
    # 最近一次闸门 / diff 决定，供路由：freeze|revise|reaudit|apply|discard（transient）
    consistency_revise_note: str = ""
    # AI 修订未产出可用改动时给闸门的一行提示（gate 展示后自清）

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

    # ── Phase 2.5：章节规划（chapter_plan，滚动窗口的远端锚点）────────────────────
    # 在整书 overall_outline 与批级 arc_outline 之间的一层「中景大纲」，向前一次规划
    # CHAPTER_PLAN_WINDOW 章，每写完 CHAPTER_PLAN_STRIDE 章滚动一次。已写完的章条目
    # 永久锁定（save_chapter_plan 合并保证），只重写未写部分。
    #
    # 覆盖语义：全量覆盖返回（不用 operator.add，因为不是纯追加，是「历史保留 + 未来覆盖」）。
    chapter_plan: list[ChapterPlanItem] = field(default_factory=list)
    # 已被覆盖到的最远章号（1-based）；供路由与前端用于展示「已规划到第 N 章」。
    chapter_plan_planned_upto: int = 0
    # 上一次触发重规划时 total_chapters_written 的值；用于 STRIDE 判定，避免同一进度重复触发。
    chapter_plan_last_regen_at: int = 0

    # ── Phase 2.5：批次小号大纲（arc outline）────────────────────────────────────
    current_arc_outline: str = ""
    # 本批章节的故事弧线大纲（每批开始时由 save_arc_outline 覆盖写入，直接注入 system_context）

    # ── Phase 2.7：章级 scene beats（可跳步骤，写正文前先规划本章节拍）──────────
    # 章级 transient：每章由 scene_beats_step 覆盖写入（可跳过），供 prepare_chapter 注入
    # chapter_prompt；save_chapter 之后由 chapter loop 清零，防止下一章跳过 gate 时误用上一章的 beats。
    # 结构：list[dict]，每个 beat 含 id / scene / goal / obstacle / outcome / cost / emotion_arc /
    # device_tags / target_words 字段，落地格式详见 prompts/scene_beats.py。
    current_chapter_beats: list = field(default_factory=list)
    # 章号锚定：记录 current_chapter_beats 是为哪一章生成的（1-based 全书章号）。prepare_chapter
    # 严格核对 beats_chapter_index == chapter_num 才注入；不匹配（跳过 gate / 上一章残留）时视同无 beats。
    # 初始 -1 = 从未生成过。
    beats_chapter_index: int = -1

    # ── Phase 2.7：统一实体卡库（EntityCard：人物/物品/装备/势力/地点）──────────────
    # 全书累积卡库——章前 entity_cards_step 为本章新登场实体建卡、章末 entity_discover_step
    # 从正文补卡 + 更新动态字段。装备/物品的唯一真源（phase_summary 不再存装备）。
    # 覆盖语义：save 端按 name+aliases 归一化去重 merge（已有锁定只追加，新增 append），
    # 参照 chapter_plan 的「历史锁定+增量」，不用 operator.add（否则压缩无法移除/改写旧卡）。
    entity_cards: list[EntityCard] = field(default_factory=list)
    # 本章登场实体名单（transient，含新+旧全部登场者）；供 prepare_chapter 触发式注入对应卡。
    current_chapter_cast: list = field(default_factory=list)
    # 章号锚定（同 beats_chapter_index 套路）：记录 current_chapter_cast 为哪一章生成。
    # prepare_chapter 严格核对 cast_chapter_index == chapter_num 才注入；不匹配（跳过 gate /
    # 上一章残留）视同无登场名单。初始 -1 = 从未生成过。
    cast_chapter_index: int = -1

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
