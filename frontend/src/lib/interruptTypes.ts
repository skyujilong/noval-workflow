// 各 interrupt() payload 类型定义 + 权威 type 分发。
// payload 结构来自源码核实（subgraph.py / chapter_plan_edit_subgraph.py / edit_step_subgraph.py /
// nodes/inputs.py / nodes/chapter.py）。后端 interrupt() 必带 type 字段（见后端
// InterruptType 枚举），前端按 type 显式查表分发，不再依赖 message 文案匹配。

// ── InterruptType 枚举（镜像 src/novel_workflow/interrupt_types.py）──────────────
// 作为前后端 API 契约：每个 interrupt 点的"唯一标识"。新增 interrupt 时需同步两边。
export const InterruptType = {
  // Phase -1：灵感脑爆（可选，入口分叉）
  BRAINSTORM_GATE: "brainstorm_gate",
  BRAINSTORM_CHAT: "brainstorm_chat",
  // 脑爆结束轮的完整版确认闸门：finalize 流式生成 markdown 完整版后停下，让用户从 AI 气泡下方
  // 「使用这份产物」/「返回脑爆继续」二选一。此 interrupt 期间禁用聊天输入，避免语义混乱。
  BRAINSTORM_FINALIZE_CONFIRM: "brainstorm_finalize_confirm",
  // 脑爆结束后的整合 review：一次性 review + 编辑 4 个正式设定字段，取代下面 4 个逐项 confirm
  BRAINSTORM_EXTRACT_REVIEW: "brainstorm_extract_review",
  // 以下 4 个 confirm 已被 BRAINSTORM_EXTRACT_REVIEW 合并接管；类型与组件保留供快速回滚
  BRAINSTORM_CORE_THEME_CONFIRM: "brainstorm_core_theme_confirm",
  BRAINSTORM_WORLD_BUILDING_CONFIRM: "brainstorm_world_building_confirm",
  BRAINSTORM_POWER_SYSTEM_CONFIRM: "brainstorm_power_system_confirm",
  BRAINSTORM_CORE_CONFLICTS_CONFIRM: "brainstorm_core_conflicts_confirm",
  // 用户输入阶段
  USER_INPUTS: "user_inputs",
  USER_INPUTS_ERROR: "user_inputs_error",
  // 章末长线章节规划调整步骤（chapter_plan_edit_subgraph）：调远端锚点，弧线自动派生跟随
  CHAPTER_PLAN_EDIT_ENTRY_GATE: "chapter_plan_edit_entry_gate",
  CHAPTER_PLAN_EDIT_DIRECTION: "chapter_plan_edit_direction",
  CHAPTER_PLAN_EDIT_CONFIRM: "chapter_plan_edit_confirm",
  CHAPTER_PLAN_EDIT_CONFIRM_ERROR: "chapter_plan_edit_confirm_error",
  // 旧「直接手改弧线」步骤：已被 CHAPTER_PLAN_EDIT_* 取代（弧线改为纯派生），保留供回滚
  ARC_ENTRY_GATE: "arc_entry_gate",
  ARC_DIRECTION_INPUT: "arc_direction_input",
  ARC_CONFIRM: "arc_confirm",
  ARC_CONFIRM_ERROR: "arc_confirm_error",
  // 弧线联动标题确认（chapter_plan 编辑收尾仍复用）
  ARC_TITLES_CONFIRM: "arc_titles_confirm",
  // 人物动态状态/关系已并入 CharacterCard（current_state/relations/standing），
  // 原 status/relations 两条独立快照腿已删；动态更新走章末 entity_discover。
  // 伏笔台账快照（foreshadowing）
  FORESHADOWING_ENTRY_GATE: "foreshadowing_entry_gate",
  FORESHADOWING_DIRECTION_INPUT: "foreshadowing_direction_input",
  FORESHADOWING_REVIEW: "foreshadowing_review",
  // 阶段固化数据快照（phase_summary）
  PHASE_SUMMARY_ENTRY_GATE: "phase_summary_entry_gate",
  PHASE_SUMMARY_DIRECTION_INPUT: "phase_summary_direction_input",
  PHASE_SUMMARY_REVIEW: "phase_summary_review",
  // 章级 scene beats（章前节拍表，可跳步骤；插在 save_titles 之后、prepare_chapter 之前）
  SCENE_BEATS_ENTRY_GATE: "scene_beats_entry_gate",
  SCENE_BEATS_DIRECTION_INPUT: "scene_beats_direction_input",
  SCENE_BEATS_REVIEW: "scene_beats_review",
  // 章级角色档案发现已废弃——人物档案并入 entity_cards，发现/更新统一走章前 entity_cards
  // + 章末 entity_discover，不再有独立的 character_profiles_discover 腿。
  // 章前登场实体卡（EntityCard；插在 scene_beats 之后、prepare_chapter 之前）
  ENTITY_CARDS_ENTRY_GATE: "entity_cards_entry_gate",
  ENTITY_CARDS_DIRECTION_INPUT: "entity_cards_direction_input",
  ENTITY_CARDS_REVIEW: "entity_cards_review",
  // 章末实体发现 + 动态更新（插在 chapter_edit_subgraph 的 phase_step 之后）
  ENTITY_DISCOVER_ENTRY_GATE: "entity_discover_entry_gate",
  ENTITY_DISCOVER_DIRECTION_INPUT: "entity_discover_direction_input",
  ENTITY_DISCOVER_REVIEW: "entity_discover_review",
  // 通用审核（基础设定类、标题、弧线大纲等共用 review_generic；章节正文 review_chapter）
  REVIEW_GENERIC: "review_generic",
  REVIEW_CHAPTER: "review_chapter",
  // 分卷边界闸门（Volume boundary gate；chapter_plan 前瞻窗口穿越卷 target 边界时触发）
  VOLUME_BOUNDARY_GATE: "volume_boundary_gate",
  // 其他
  ASK_CONTINUE: "ask_continue",
  CONSISTENCY_GATE: "consistency_gate", // 设定一致性总审闸门（save_config 冻结前，跨设定终审）
  CONSISTENCY_DIFF: "consistency_diff", // 一致性总审 · AI 修订改前/改后 diff 审核闸门
  // 伏笔台账精简流程
  FORESHADOW_PRUNE_ASK: "foreshadow_prune_ask",
  FORESHADOW_PRUNE_CONFIRM: "foreshadow_prune_confirm",
  // 章末实体发现·入库筛选（产出时勾选哪些 new_cards/updates 真正入库）
  ENTITY_SELECT_CONFIRM: "entity_select_confirm",
  // 章末实体卡库精简（LLM 分析整库，人工勾选整卡删除；ASK 复用 entry_gate 是/否）
  ENTITY_CARDS_PRUNE_ASK: "entity_cards_prune_ask",
  ENTITY_CARDS_PRUNE_CONFIRM: "entity_cards_prune_confirm",
} as const;

export type InterruptTypeValue = (typeof InterruptType)[keyof typeof InterruptType];

// ── 各中断点的 payload 形态 ────────────────────────────────────────────────────
// 每个 payload 都带 type 字段（权威契约），其余为该表单所需的结构化数据。

export interface UserInputsPayload {
  type: InterruptTypeValue;
  message: string;
  fields: Record<string, string>; // 字段名 → 说明
  current_values: Record<string, string>;
}
export interface UserInputsErrorPayload {
  type: InterruptTypeValue;
  error: string;
  required_fields: string[];
  received: string;
}
export interface MessageOnlyPayload {
  type: InterruptTypeValue;
  message: string;
}

/** 脑爆多轮聊天 payload（brainstorm_chat）：携带概要 + 完整近期历史，前端直接渲染。
 * has_power_system 供聊天页底部 switch 显示初值；用户切换时前端调 updateThreadState 直接写回
 * state（不清 interrupt），下轮进本节点时后端从 state 读到最新值。 */
export interface BrainstormChatPayload {
  type: InterruptTypeValue;
  message: string;
  brainstorm_summary: string;
  brainstorm_history: Array<{ role: "human" | "ai"; content: string }>;
  has_power_system: boolean;
}

/** 脑爆产物轻量确认 payload（core_theme / world_building / core_conflicts）：展示内容供确认或编辑。 */
export interface BrainstormConfirmPayload {
  type: InterruptTypeValue;
  title: string; // 确认项名称（核心主题 / 世界观 / 核心冲突），用于区分表单标题
  message: string;
  field: string;
  content: string;
}

/**
 * 脑爆产物整合 review payload：一次性 review + 编辑 4 个正式设定字段 + 7 个基础参数字段。
 * has_power_system 反映 state 里的作品级决策（初始由题材默认建议，用户可在抽屉里覆盖），
 * 前端据此决定 checkbox 初始状态与力量体系编辑区显隐。
 * missing_fields 由 v2 finalize_confirm 节点纯 python 切分后累积——切不到内容的字段名列表，
 * 前端在对应 FieldBlock 头部挂黄色警告，提示用户手填或返回脑爆补充。
 *
 * 7 基础参数字段由后端 _extract_basic_fields 在 brainstorm_finalize_confirm 时预填（可能有值可能空），
 * 前端渲染专区让用户 review + 修改。allowed_genres 为 genre 下拉候选，缺失时前端 fallback
 * 到硬编码六选一。
 */
export interface BrainstormExtractReviewPayload {
  type: InterruptTypeValue;
  message: string;
  core_theme: string;
  world_building: string;
  power_system: string;
  core_conflicts: string;
  has_power_system: boolean;
  missing_fields: string[];
  // 7 基础参数（新增。老后端不带这些键 → undefined → 前端渲染空 input）
  novel_name?: string;
  genre?: string;
  writing_style?: string;
  target_audience?: string;
  core_tone?: string;
  chapter_word_count?: string;
  total_word_count?: string;
  // genre 下拉候选（新增。老后端不带 → 前端 fallback 到硬编码六选一）
  allowed_genres?: string[];
}

/**
 * 脑爆结束轮完整版确认闸门 payload。finalize 节点已经把这份 markdown 流式打到聊天页 AI 气泡末尾，
 * 前端主要靠此 interrupt 的存在决定「在聊天页 AI 气泡下方渲染两个按钮 + 禁用输入框」。
 * finalize_markdown 冗余透传，供前端自查 / 调试；正常渲染路径直接读 state.brainstorm_history 末条。
 */
export interface BrainstormFinalizeConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  finalize_markdown: string;
  has_power_system: boolean;
}
export interface AskContinuePayload {
  type: InterruptTypeValue;
  message: string;
  total_chapters_written: number;
}

/** 设定一致性总审闸门 payload：报告走 message（whitespace-pre-wrap 渲染）；can_revise 决定是否给「让 AI 修订」。 */
export interface ConsistencyGatePayload {
  type: InterruptTypeValue;
  message: string;
  can_revise: boolean;
}

/** 一致性总审 · AI 修订单条提案：某设定项的改前/改后 + 修订理由。 */
export interface ConsistencyRevision {
  field: string;
  label: string;
  before: string;
  after: string;
  reason?: string;
}

/** AI 修订 diff 审核闸门 payload：逐项 revisions 供高亮 diff 展示 + 逐项编辑。 */
export interface ConsistencyDiffPayload {
  type: InterruptTypeValue;
  message: string;
  revisions: ConsistencyRevision[];
}
export interface ArcDirectionPayload {
  type: InterruptTypeValue;
  message: string;
  current_arc_outline: string;
  remaining_titles: string[];
}
export interface ArcConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  ai_generated_arc: string;
}
export interface ArcConfirmErrorPayload {
  type: InterruptTypeValue;
  message: string;
  error: string;
}
export interface ArcTitlesConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  ai_generated_titles: string[];
  shortage: number;
}

/** 章节规划条目（远端锚点单条）——与后端 ChapterPlanItem 一致，供编辑表单渲染 ChapterPlanCards。 */
export interface ChapterPlanEditItem {
  chapter: number;
  purpose: string;
  key_turn: string;
  ending_hook: string;
  intensity?: string;
}
/** 章末长线章节规划调整 · 是否执行闸门 payload（cp_entry）：展示未写窗口锚点 + 跳过/执行。 */
export interface ChapterPlanEditEntryGatePayload {
  type: InterruptTypeValue;
  message: string;
  chapter_plan_window: ChapterPlanEditItem[];
  range: [number, number];
}
/** 章末长线章节规划调整 · 方向输入 payload（cp_direction）：展示未写窗口锚点 + 输入调整方向。 */
export interface ChapterPlanEditDirectionPayload {
  type: InterruptTypeValue;
  message: string;
  chapter_plan_window: ChapterPlanEditItem[];
  range: [number, number];
}
/** 章末长线章节规划调整 · AI 结果确认 payload（cp_confirm）：展示 AI 重规划的未写段草稿。 */
export interface ChapterPlanEditConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  ai_chapter_plan: ChapterPlanEditItem[];
}
/** 章末长线章节规划调整 · AI 失败手动兜底 payload（cp_confirm_error）。 */
export interface ChapterPlanEditConfirmErrorPayload {
  type: InterruptTypeValue;
  message: string;
  error: string;
}

/**
 * human_review 富审稿表单 payload。
 * 后端 subgraph.py:human_review 把草稿/AI 自审意见/修改历史/review_type/轮次一并塞入，
 * 前端直接读，无需再调 getSubgraphState（后者在嵌套子图冒泡时会选错 task）。
 */
export interface HumanReviewPayload {
  type: InterruptTypeValue;
  message: string;
  review_type: string;
  current_draft: string;
  review_feedback: string;
  review_history: Array<{ role: "human" | "ai"; content: string }>;
  llm_review_count: number;
  llm_review_max: number;
  // 当前 review_type 的默认深度思考状态，用于初始化「深度思考」开关位置
  default_thinking?: "enabled" | "disabled";
}

/**
 * 伏笔精简确认表单 payload。
 * 由 LLM 分析后生成建议，人工确认是否删除。
 */
export interface ForeshadowPruneConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  s_level_count: number; // S级核心伏笔数量
  a_level_count: number; // A级次要伏笔数量
  to_delete: Array<{
    id: string;
    name: string;
    reason: string;
    planted_batch?: number;
    freedom?: string;
  }>; // 建议删除的伏笔列表
  suggestion: string; // 整体精简建议
  pending_count: number; // 当前悬置伏笔总数
  collected_count: number; // 当前已收伏笔总数
}

/**
 * 章末实体发现·入库筛选 payload。
 * 展示本章 LLM 发现的 new_cards（新建卡）与 updates（已有卡动态更新），
 * 让用户勾选真正入库的项，剔除一次性碎屑。resume 值 = 选中 key 的 JSON 数组。
 */
export interface EntitySelectConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  new_cards: Array<{
    key: string; // 稳定 key，如 "new:圣焰皇家骑士团"
    name: string;
    type: string; // 人物/物品/装备/势力/地点
    summary: string;
  }>;
  updates: Array<{
    key: string; // 稳定 key，如 "update:陆默"
    name: string;
    changes: Record<string, string>; // 本条改动的动态字段 → 新值
  }>;
}

/**
 * 章末实体卡库精简确认 payload。
 * 展示**全部**卡（不只 AI 建议删的），suggested=true 的默认预选、附 reason；
 * 用户可自行增减后提交。resume 值 = 选中删除的实体名 JSON 数组，如 ["张三","遣散费"]，
 * 空数组表示不删除任何卡。定位主键是实体 name（卡库以 name 归一去重）。
 */
export interface EntityCardsPruneConfirmPayload {
  type: InterruptTypeValue;
  message: string;
  cards: Array<{
    name: string;
    type: string; // 人物/物品/装备/势力/地点
    role: string; // 人物卡的角色定位，非人物为空
    summary: string;
    current_state: string;
    first_appear_chapter: number | null;
    suggested: boolean; // AI 是否建议删除（用于默认预选）
    reason: string; // AI 建议删除的理由（suggested=true 时非空）
  }>;
  suggestion: string; // 整体精简说明
  suggested_count: number; // AI 建议删除张数
  total_count: number; // 卡库总张数
}

// ── type → 表单种类 分发 ───────────────────────────────────────────────────────

export type FormKind =
  | "brainstorm_gate"
  | "brainstorm_chat"
  | "brainstorm_confirm"
  | "brainstorm_extract_review"
  | "brainstorm_finalize_confirm"
  | "user_inputs"
  | "human_review"
  | "ask_continue"
  | "entry_gate"
  | "direction"
  | "arc_direction"
  | "arc_confirm"
  | "arc_titles_confirm"
  | "chapter_plan_edit_direction"
  | "chapter_plan_edit_confirm"
  | "foreshadowing_review"
  | "foreshadow_prune_confirm"
  | "entity_select_confirm"
  | "entity_cards_prune_confirm"
  | "consistency_gate"
  | "consistency_diff"
  | "volume_boundary_gate"
  | "unknown";

/**
 * 每个 InterruptType 显式映射到表单种类。多个 type 可指向同一表单
 * （如所有 *_review → human_review，所有 *_entry_gate → entry_gate）。
 * 新增 interrupt 类型时必须在此登记，否则落到 unknown 显式暴露。
 */
const TYPE_TO_FORM: Record<InterruptTypeValue, FormKind> = {
  [InterruptType.BRAINSTORM_GATE]: "brainstorm_gate",
  [InterruptType.BRAINSTORM_CHAT]: "brainstorm_chat",
  [InterruptType.BRAINSTORM_FINALIZE_CONFIRM]: "brainstorm_finalize_confirm",
  [InterruptType.BRAINSTORM_EXTRACT_REVIEW]: "brainstorm_extract_review",
  [InterruptType.BRAINSTORM_CORE_THEME_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_WORLD_BUILDING_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_POWER_SYSTEM_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_CORE_CONFLICTS_CONFIRM]: "brainstorm_confirm",

  [InterruptType.USER_INPUTS]: "user_inputs",
  [InterruptType.USER_INPUTS_ERROR]: "user_inputs",

  [InterruptType.CHAPTER_PLAN_EDIT_ENTRY_GATE]: "entry_gate",
  [InterruptType.ARC_ENTRY_GATE]: "entry_gate",
  [InterruptType.FORESHADOWING_ENTRY_GATE]: "entry_gate",
  [InterruptType.PHASE_SUMMARY_ENTRY_GATE]: "entry_gate",
  [InterruptType.SCENE_BEATS_ENTRY_GATE]: "entry_gate",
  [InterruptType.ENTITY_CARDS_ENTRY_GATE]: "entry_gate",
  [InterruptType.ENTITY_DISCOVER_ENTRY_GATE]: "entry_gate",

  // 弧线方向单独识别（标题为"弧线大纲调整方向"），其余 step 方向归入 direction
  [InterruptType.ARC_DIRECTION_INPUT]: "arc_direction",
  [InterruptType.FORESHADOWING_DIRECTION_INPUT]: "direction",
  [InterruptType.PHASE_SUMMARY_DIRECTION_INPUT]: "direction",
  [InterruptType.SCENE_BEATS_DIRECTION_INPUT]: "direction",
  [InterruptType.ENTITY_CARDS_DIRECTION_INPUT]: "direction",
  [InterruptType.ENTITY_DISCOVER_DIRECTION_INPUT]: "direction",

  [InterruptType.FORESHADOWING_REVIEW]: "foreshadowing_review", // 伏笔专用表单
  [InterruptType.PHASE_SUMMARY_REVIEW]: "human_review",
  [InterruptType.SCENE_BEATS_REVIEW]: "human_review",
  [InterruptType.ENTITY_CARDS_REVIEW]: "human_review",
  [InterruptType.ENTITY_DISCOVER_REVIEW]: "human_review",
  [InterruptType.REVIEW_GENERIC]: "human_review",
  [InterruptType.REVIEW_CHAPTER]: "human_review",

  [InterruptType.ARC_CONFIRM]: "arc_confirm",
  [InterruptType.ARC_CONFIRM_ERROR]: "arc_confirm",
  [InterruptType.ARC_TITLES_CONFIRM]: "arc_titles_confirm",

  // 章末长线章节规划调整
  [InterruptType.CHAPTER_PLAN_EDIT_DIRECTION]: "chapter_plan_edit_direction",
  [InterruptType.CHAPTER_PLAN_EDIT_CONFIRM]: "chapter_plan_edit_confirm",
  [InterruptType.CHAPTER_PLAN_EDIT_CONFIRM_ERROR]: "chapter_plan_edit_confirm",

  [InterruptType.ASK_CONTINUE]: "ask_continue",
  // 一致性总审：专用三选表单（通过冻结 / 让 AI 修订 / 重新审查），报告走 message 由 whitespace-pre-wrap 渲染
  [InterruptType.CONSISTENCY_GATE]: "consistency_gate",
  // AI 修订改前/改后 diff 审核（逐项高亮 diff + 可编辑 + 应用/放弃）
  [InterruptType.CONSISTENCY_DIFF]: "consistency_diff",
  [InterruptType.FORESHADOW_PRUNE_ASK]: "entry_gate", // 复用 entry_gate 形式（是/否）
  [InterruptType.FORESHADOW_PRUNE_CONFIRM]: "foreshadow_prune_confirm", // 专用确认表单
  [InterruptType.ENTITY_SELECT_CONFIRM]: "entity_select_confirm", // 入库筛选专用勾选表单
  [InterruptType.ENTITY_CARDS_PRUNE_ASK]: "entry_gate", // 复用 entry_gate 形式（是/否）
  [InterruptType.ENTITY_CARDS_PRUNE_CONFIRM]: "entity_cards_prune_confirm", // 卡库精简专用勾选表单
  // 分卷边界闸门：专用 3 选 1 表单（继续本卷 / 收卷 / 延长 target_max）
  [InterruptType.VOLUME_BOUNDARY_GATE]: "volume_boundary_gate",
};

/**
 * 根据 payload.type 查表得到表单种类。
 * type 缺失或未登记 → unknown（视为后端契约故障，由 InterruptHandler 显式暴露，
 * 不做 message 文案兜底，避免掩盖真实问题）。
 */
export function formKindFromType(type: unknown): FormKind {
  if (typeof type !== "string") return "unknown";
  return (TYPE_TO_FORM as Record<string, FormKind>)[type] ?? "unknown";
}

/** 从 payload 中安全提取 type 并查表分发（InterruptHandler 入口） */
export function formKindOfPayload(payload: unknown): FormKind {
  if (!payload || typeof payload !== "object") return "unknown";
  return formKindFromType((payload as { type?: unknown }).type);
}

/**
 * 各 direction_input 类型 → DirectionForm 标题（由 payload.type 派生，贯彻 type 自描述）。
 * 未登记的回退到通用「调整方向」。新增 *_DIRECTION_INPUT 时在此登记即可，无需改组件。
 */
const DIRECTION_TITLE: Record<string, string> = {
  [InterruptType.ARC_DIRECTION_INPUT]: "弧线大纲调整方向",
  [InterruptType.FORESHADOWING_DIRECTION_INPUT]: "伏笔台账调整方向",
  [InterruptType.PHASE_SUMMARY_DIRECTION_INPUT]: "阶段固化数据调整方向",
  [InterruptType.SCENE_BEATS_DIRECTION_INPUT]: "Scene beats 调整方向",
  [InterruptType.ENTITY_CARDS_DIRECTION_INPUT]: "登场实体卡调整方向",
  [InterruptType.ENTITY_DISCOVER_DIRECTION_INPUT]: "实体发现/更新调整方向",
};

/** 按 direction payload.type 查标题，未知 type 回退「调整方向」 */
export function directionTitleOf(type: unknown): string {
  return (typeof type === "string" && DIRECTION_TITLE[type]) || "调整方向";
}

/**
 * 各 entry_gate 类型 → EntryGateForm 标题（由 payload.type 派生，贯彻 type 自描述）。
 * make_edit_step_subgraph 产出的 *_entry_gate 全共用同一张 EntryGateForm，标题不派生就一律
 * 显示默认「步骤确认」，用户分不清是哪一步的执行/跳过闸门。未登记的回退到通用「步骤确认」。
 * 新增 *_ENTRY_GATE 时在此登记即可，无需改组件。
 */
const ENTRY_GATE_TITLE: Record<string, string> = {
  [InterruptType.CHAPTER_PLAN_EDIT_ENTRY_GATE]: "后续章节规划调整（弧线自动跟随）· 是否执行",
  [InterruptType.ARC_ENTRY_GATE]: "弧线大纲 · 是否执行",
  [InterruptType.FORESHADOWING_ENTRY_GATE]: "伏笔台账快照 · 是否执行",
  [InterruptType.PHASE_SUMMARY_ENTRY_GATE]: "阶段固化数据 · 是否执行",
  [InterruptType.SCENE_BEATS_ENTRY_GATE]: "Scene beats 节拍表 · 是否执行",
  [InterruptType.ENTITY_CARDS_ENTRY_GATE]: "章前登场实体卡 · 是否执行",
  [InterruptType.ENTITY_DISCOVER_ENTRY_GATE]: "章末实体发现 / 更新 · 是否执行",
  // 伏笔精简复用 entry_gate 形式（是/否），单独给标题
  [InterruptType.FORESHADOW_PRUNE_ASK]: "伏笔台账精简 · 是否执行",
  [InterruptType.ENTITY_CARDS_PRUNE_ASK]: "实体卡库精简 · 是否执行",
};

/** 按 entry_gate payload.type 查标题，未知 type 回退「步骤确认」 */
export function entryGateTitleOf(type: unknown): string {
  return (typeof type === "string" && ENTRY_GATE_TITLE[type]) || "步骤确认";
}

// ── resume 值构造辅助 ─────────────────────────────────────────────────────────

/** 脑爆 gate：进入脑爆（须 ∈ 后端 _ENTER_SIGNALS） */
export const BRAINSTORM_ENTER = "脑爆";
/** 脑爆 gate：直接走普通流程（非 enter 信号即可） */
export const BRAINSTORM_DIRECT = "直接";
/** 脑爆聊天：结束信号（须 ∈ 后端 _END_SIGNALS） */
export const BRAINSTORM_END = "结束脑爆";

/** resume 时表示「执行」的值（后端 step_entry/arc_entry 用 _SKIP_WORDS 判定跳过，"yes" 非跳过词即执行） */
export const EXECUTE_VALUE = "yes";
/** resume 时表示「跳过」的值（空串属于后端 _SKIP_WORDS） */
export const SKIP_VALUE = "";

/** arc_confirm / arc_titles_confirm 的「手动替换」前缀语法 */
export const MANUAL_REPLACE_PREFIX = "=";

/** 构造手动替换的 resume 值：=开头 + 内容 */
export function buildManualReplaceValue(content: string): string {
  return MANUAL_REPLACE_PREFIX + content.trim();
}

/** 继续信号集（ask_continue 的 _CONTINUE_SIGNALS） */
const CONTINUE_VALUES = new Set(["", "yes", "y", "是", "继续"]);
export function isContinueValue(v: string): boolean {
  return CONTINUE_VALUES.has(v.trim().toLowerCase());
}

/** 审核表单（human_review / foreshadowing_review）深度思考选择 */
export type ThinkingChoice = "enabled" | "disabled";

/**
 * human_review 节点的结构化 resume 值，所有走该节点的审核表单统一发送此形态。
 * - feedback：空串 = 通过；非空 = 修改意见（驱动重新生成）。
 * - thinking：本轮重生成是否深度思考（开关位置，通过场景下后端忽略）。
 */
export interface ReviewResume {
  feedback: string;
  thinking: ThinkingChoice;
}

/** 构造审核表单的结构化 resume 值（approve 传空 feedback，revise 传修改意见）。 */
export function buildReviewResume(feedback: string, thinkingOn: boolean): ReviewResume {
  return { feedback: feedback.trim(), thinking: thinkingOn ? "enabled" : "disabled" };
}

// ── 一致性总审闸门 resume 值（与后端 consistency_gate 的信号集对齐）─────────────
/** 通过冻结：采纳当前设定，进入正式创作 */
export const CONSISTENCY_FREEZE = "freeze";
/** 让 AI 修订：进入 revise → diff 审核闭环 */
export const CONSISTENCY_REVISE = "revise";
/** 重新审查：配合左侧手改设定后复审 */
export const CONSISTENCY_REAUDIT = "reaudit";

/** AI 修订 diff 闸门的结构化 resume 值。 */
export interface ConsistencyDiffApply {
  action: "apply";
  revisions: Array<{ field: string; after: string }>;
}
export interface ConsistencyDiffDiscard {
  action: "discard";
}
export type ConsistencyDiffResume = ConsistencyDiffApply | ConsistencyDiffDiscard;

/** 应用修订：把逐项（可能人工编辑过的）终稿回写。 */
export function buildConsistencyApplyResume(
  items: Array<{ field: string; after: string }>
): ConsistencyDiffApply {
  return { action: "apply", revisions: items };
}
/** 放弃修订：不改动任何设定，折返回闸门。 */
export function buildConsistencyDiscardResume(): ConsistencyDiffDiscard {
  return { action: "discard" };
}

// ── 脑爆产物整合 review 的 resume 值（与后端 brainstorm_extract_review 节点对齐）─────
/**
 * 脑爆产物整合 review 的结构化 resume 值。has_power_system 由聊天页 switch 在结束脑爆前决定
 * 并已写回 state，抽屉不再产生此值——power_system 字段仅在 has_power_system=true 时透传。
 *
 * 7 基础参数字段（novel_name / genre / writing_style / target_audience / core_tone /
 * chapter_word_count / total_word_count）由抽屉里的「全书基础参数」分区收集，用户可保留
 * 预填、修改、或主动清空（后端语义：键存在就写入，含空串——尊重"没想好"的意图，由 collect
 * 表单再兜底问一次）。
 *
 * - advance：用户 review 完成，携带编辑后字段 → 后端覆写 state + 推进到 collect_user_inputs
 * - back_to_chat：用户想再和 AI 聊几轮 → 后端不写字段、复位 brainstorm_done → 回 brainstorm_chat
 */
export interface BrainstormReviewAdvance {
  action: "advance";
  core_theme: string;
  world_building: string;
  power_system?: string;
  core_conflicts: string;
  // 7 基础参数（新增；后端向后兼容：老前端不发这些键时后端跳过写入）
  novel_name: string;
  genre: string;
  writing_style: string;
  target_audience: string;
  core_tone: string;
  chapter_word_count: string;
  total_word_count: string;
}
export interface BrainstormReviewBackToChat {
  action: "back_to_chat";
}
export type BrainstormReviewResume = BrainstormReviewAdvance | BrainstormReviewBackToChat;

/** 构造「保存并推进」resume 值。power_system 仅在调用方判定 has_power_system=true 时传入；
 * 7 基础参数字段 trim 后传入（含空串——允许用户主动清空，后端会尊重该意图）。 */
export function buildBrainstormReviewAdvanceResume(fields: {
  core_theme: string;
  world_building: string;
  power_system?: string;
  core_conflicts: string;
  novel_name: string;
  genre: string;
  writing_style: string;
  target_audience: string;
  core_tone: string;
  chapter_word_count: string;
  total_word_count: string;
}): BrainstormReviewAdvance {
  const out: BrainstormReviewAdvance = {
    action: "advance",
    core_theme: fields.core_theme.trim(),
    world_building: fields.world_building.trim(),
    core_conflicts: fields.core_conflicts.trim(),
    novel_name: fields.novel_name.trim(),
    genre: fields.genre.trim(),
    writing_style: fields.writing_style.trim(),
    target_audience: fields.target_audience.trim(),
    core_tone: fields.core_tone.trim(),
    chapter_word_count: fields.chapter_word_count.trim(),
    total_word_count: fields.total_word_count.trim(),
  };
  if (fields.power_system !== undefined) out.power_system = fields.power_system.trim();
  return out;
}

/** 构造「返回脑爆继续修改」resume 值。 */
export function buildBrainstormReviewBackResume(): BrainstormReviewBackToChat {
  return { action: "back_to_chat" };
}

// ── 脑爆完整版确认闸门 resume 值（与后端 brainstorm_finalize_confirm 节点对齐）──
/**
 * finalize_confirm 闸门的两种 resume 分支。**都是 dict**（后端契约要求）：
 * - use          → 后端纯 python 切分完整版 markdown → 覆盖 4 字段 → 进 extract_review
 * - back_to_chat → 后端剥掉 history 末条（那份完整版）+ 复位 brainstorm_done → 回聊天
 */
export interface BrainstormFinalizeConfirmUse {
  action: "use";
}
export interface BrainstormFinalizeConfirmBackToChat {
  action: "back_to_chat";
}
export type BrainstormFinalizeConfirmResume =
  | BrainstormFinalizeConfirmUse
  | BrainstormFinalizeConfirmBackToChat;

/** 构造「使用这份产物」resume 值。 */
export function buildFinalizeConfirmUse(): BrainstormFinalizeConfirmUse {
  return { action: "use" };
}
/** 构造「返回脑爆继续」resume 值。语义上与 review 面板的 back_to_chat 等价，但走的是不同节点，
 * 为了类型明确保留独立 builder。 */
export function buildFinalizeConfirmBackToChat(): BrainstormFinalizeConfirmBackToChat {
  return { action: "back_to_chat" };
}

// ── 分卷边界闸门 payload + resume 值（与后端 nodes/volume_gate.py 对齐）─────────

/** 单条穿越点：本次 chapter_plan 窗口穿到了某卷的 target_min 或 target_max。 */
export interface VolumeBoundaryCrossing {
  volume_index: number;
  kind: "target_min" | "target_max";
  chapter: number;
}

/** 卷条目 dict 快照（interrupt payload 用；结构与 Volume interface 一致，但由后端 dataclass → dict 转换）。 */
export interface VolumeDictSnapshot {
  index: number;
  title: string;
  summary: string;
  setup_for_next: string;
  chapter_start: number;
  target_min: number;
  target_max: number;
  actual_end: number | null;
  status: string;
}

/** 三选一选项，后端在 volume_gate.py 里构造。 */
export interface VolumeBoundaryOption {
  action: "continue_current" | "close_at" | "extend_target_max";
  label: string;
  suggested_chapter?: number;
  suggested_target_max?: number;
}

/**
 * VOLUME_BOUNDARY_GATE payload。字段与 nodes/volume_gate.py::volume_boundary_gate 构造的 dict 完全一致。
 * window / crossings / current_volume / next_volumes / options 用于渲染表单展示与默认值。
 */
export interface VolumeBoundaryGatePayload {
  type: InterruptTypeValue;
  window: [number, number];
  crossings: VolumeBoundaryCrossing[];
  current_volume: VolumeDictSnapshot;
  next_volumes: VolumeDictSnapshot[];
  message: string;
  options: VolumeBoundaryOption[];
}

/** 分卷闸门三分支的结构化 resume 值。 */
export interface VolumeGateContinueCurrent {
  action: "continue_current";
}
export interface VolumeGateCloseAt {
  action: "close_at";
  chapter: number;
}
export interface VolumeGateExtendTargetMax {
  action: "extend_target_max";
  target_max: number;
}
export type VolumeGateResume =
  | VolumeGateContinueCurrent
  | VolumeGateCloseAt
  | VolumeGateExtendTargetMax;

/** 「继续本卷」resume 值（无附加字段）。 */
export function buildVolumeContinueResume(): VolumeGateContinueCurrent {
  return { action: "continue_current" };
}
/** 「在第 X 章收卷」resume 值。 */
export function buildVolumeCloseAtResume(chapter: number): VolumeGateCloseAt {
  return { action: "close_at", chapter };
}
/** 「延长本卷 target_max 到 N」resume 值。 */
export function buildVolumeExtendResume(target_max: number): VolumeGateExtendTargetMax {
  return { action: "extend_target_max", target_max };
}
