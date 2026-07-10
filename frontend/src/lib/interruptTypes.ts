// 各 interrupt() payload 类型定义 + 权威 type 分发。
// payload 结构来自源码核实（subgraph.py / arc_edit_subgraph.py / edit_step_subgraph.py /
// nodes/inputs.py / nodes/chapter.py）。后端 interrupt() 必带 type 字段（见后端
// InterruptType 枚举），前端按 type 显式查表分发，不再依赖 message 文案匹配。

// ── InterruptType 枚举（镜像 src/novel_workflow/interrupt_types.py）──────────────
// 作为前后端 API 契约：每个 interrupt 点的"唯一标识"。新增 interrupt 时需同步两边。
export const InterruptType = {
  // Phase -1：灵感脑爆（可选，入口分叉）
  BRAINSTORM_GATE: "brainstorm_gate",
  BRAINSTORM_CHAT: "brainstorm_chat",
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
  // 弧线大纲步骤（arc_edit_subgraph）
  ARC_ENTRY_GATE: "arc_entry_gate",
  ARC_DIRECTION_INPUT: "arc_direction_input",
  ARC_CONFIRM: "arc_confirm",
  ARC_CONFIRM_ERROR: "arc_confirm_error",
  ARC_TITLES_CONFIRM: "arc_titles_confirm",
  // 人物动态状态快照（edit_step_subgraph 实例：status）
  STATUS_ENTRY_GATE: "status_entry_gate",
  STATUS_DIRECTION_INPUT: "status_direction_input",
  STATUS_REVIEW: "status_review",
  // 人物关系/势力格局快照（relations）
  RELATIONS_ENTRY_GATE: "relations_entry_gate",
  RELATIONS_DIRECTION_INPUT: "relations_direction_input",
  RELATIONS_REVIEW: "relations_review",
  // 伏笔台账快照（foreshadowing）
  FORESHADOWING_ENTRY_GATE: "foreshadowing_entry_gate",
  FORESHADOWING_DIRECTION_INPUT: "foreshadowing_direction_input",
  FORESHADOWING_REVIEW: "foreshadowing_review",
  // 阶段固化数据快照（phase_summary）
  PHASE_SUMMARY_ENTRY_GATE: "phase_summary_entry_gate",
  PHASE_SUMMARY_DIRECTION_INPUT: "phase_summary_direction_input",
  PHASE_SUMMARY_REVIEW: "phase_summary_review",
  // 通用审核（基础设定类、标题、弧线大纲等共用 review_generic；章节正文 review_chapter）
  REVIEW_GENERIC: "review_generic",
  REVIEW_CHAPTER: "review_chapter",
  // 其他
  ASK_CONTINUE: "ask_continue",
  CONSISTENCY_GATE: "consistency_gate", // 设定一致性总审闸门（save_config 冻结前，跨设定终审）
  CONSISTENCY_DIFF: "consistency_diff", // 一致性总审 · AI 修订改前/改后 diff 审核闸门
  // 伏笔台账精简流程
  FORESHADOW_PRUNE_ASK: "foreshadow_prune_ask",
  FORESHADOW_PRUNE_CONFIRM: "foreshadow_prune_confirm",
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
 * 脑爆产物整合 review payload：一次性 review + 编辑 4 个正式设定字段。
 * has_power_system 反映 state 里的作品级决策（初始由题材默认建议，用户可在抽屉里覆盖），
 * 前端据此决定 checkbox 初始状态与力量体系编辑区显隐。
 * finalize_summary 是结束脑爆时 AI 自然语言收尾原文（chat 气泡里那段流式内容的同一份），
 * 面板顶部只读展示——旧 thread 缺失时前端隐藏该展示区，向后兼容。
 */
export interface BrainstormExtractReviewPayload {
  type: InterruptTypeValue;
  message: string;
  finalize_summary?: string;
  core_theme: string;
  world_building: string;
  power_system: string;
  core_conflicts: string;
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

// ── type → 表单种类 分发 ───────────────────────────────────────────────────────

export type FormKind =
  | "brainstorm_gate"
  | "brainstorm_chat"
  | "brainstorm_confirm"
  | "brainstorm_extract_review"
  | "user_inputs"
  | "human_review"
  | "ask_continue"
  | "entry_gate"
  | "direction"
  | "arc_direction"
  | "arc_confirm"
  | "arc_titles_confirm"
  | "foreshadowing_review"
  | "foreshadow_prune_confirm"
  | "consistency_gate"
  | "consistency_diff"
  | "unknown";

/**
 * 每个 InterruptType 显式映射到表单种类。多个 type 可指向同一表单
 * （如所有 *_review → human_review，所有 *_entry_gate → entry_gate）。
 * 新增 interrupt 类型时必须在此登记，否则落到 unknown 显式暴露。
 */
const TYPE_TO_FORM: Record<InterruptTypeValue, FormKind> = {
  [InterruptType.BRAINSTORM_GATE]: "brainstorm_gate",
  [InterruptType.BRAINSTORM_CHAT]: "brainstorm_chat",
  [InterruptType.BRAINSTORM_EXTRACT_REVIEW]: "brainstorm_extract_review",
  [InterruptType.BRAINSTORM_CORE_THEME_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_WORLD_BUILDING_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_POWER_SYSTEM_CONFIRM]: "brainstorm_confirm",
  [InterruptType.BRAINSTORM_CORE_CONFLICTS_CONFIRM]: "brainstorm_confirm",

  [InterruptType.USER_INPUTS]: "user_inputs",
  [InterruptType.USER_INPUTS_ERROR]: "user_inputs",

  [InterruptType.ARC_ENTRY_GATE]: "entry_gate",
  [InterruptType.STATUS_ENTRY_GATE]: "entry_gate",
  [InterruptType.RELATIONS_ENTRY_GATE]: "entry_gate",
  [InterruptType.FORESHADOWING_ENTRY_GATE]: "entry_gate",
  [InterruptType.PHASE_SUMMARY_ENTRY_GATE]: "entry_gate",

  // 弧线方向单独识别（标题为"弧线大纲调整方向"），其余 step 方向归入 direction
  [InterruptType.ARC_DIRECTION_INPUT]: "arc_direction",
  [InterruptType.STATUS_DIRECTION_INPUT]: "direction",
  [InterruptType.RELATIONS_DIRECTION_INPUT]: "direction",
  [InterruptType.FORESHADOWING_DIRECTION_INPUT]: "direction",
  [InterruptType.PHASE_SUMMARY_DIRECTION_INPUT]: "direction",

  [InterruptType.STATUS_REVIEW]: "human_review",
  [InterruptType.RELATIONS_REVIEW]: "human_review",
  [InterruptType.FORESHADOWING_REVIEW]: "foreshadowing_review", // 伏笔专用表单
  [InterruptType.PHASE_SUMMARY_REVIEW]: "human_review",
  [InterruptType.REVIEW_GENERIC]: "human_review",
  [InterruptType.REVIEW_CHAPTER]: "human_review",

  [InterruptType.ARC_CONFIRM]: "arc_confirm",
  [InterruptType.ARC_CONFIRM_ERROR]: "arc_confirm",
  [InterruptType.ARC_TITLES_CONFIRM]: "arc_titles_confirm",

  [InterruptType.ASK_CONTINUE]: "ask_continue",
  // 一致性总审：专用三选表单（通过冻结 / 让 AI 修订 / 重新审查），报告走 message 由 whitespace-pre-wrap 渲染
  [InterruptType.CONSISTENCY_GATE]: "consistency_gate",
  // AI 修订改前/改后 diff 审核（逐项高亮 diff + 可编辑 + 应用/放弃）
  [InterruptType.CONSISTENCY_DIFF]: "consistency_diff",
  [InterruptType.FORESHADOW_PRUNE_ASK]: "entry_gate", // 复用 entry_gate 形式（是/否）
  [InterruptType.FORESHADOW_PRUNE_CONFIRM]: "foreshadow_prune_confirm", // 专用确认表单
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
  [InterruptType.STATUS_DIRECTION_INPUT]: "人物动态状态调整方向",
  [InterruptType.RELATIONS_DIRECTION_INPUT]: "人物关系调整方向",
  [InterruptType.FORESHADOWING_DIRECTION_INPUT]: "伏笔台账调整方向",
  [InterruptType.PHASE_SUMMARY_DIRECTION_INPUT]: "阶段固化数据调整方向",
};

/** 按 direction payload.type 查标题，未知 type 回退「调整方向」 */
export function directionTitleOf(type: unknown): string {
  return (typeof type === "string" && DIRECTION_TITLE[type]) || "调整方向";
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
 * - advance：用户 review 完成，携带编辑后 4 字段 → 后端覆写 state + 推进到 collect_user_inputs
 * - back_to_chat：用户想再和 AI 聊几轮 → 后端不写字段、复位 brainstorm_done → 回 brainstorm_chat
 */
export interface BrainstormReviewAdvance {
  action: "advance";
  core_theme: string;
  world_building: string;
  power_system?: string;
  core_conflicts: string;
}
export interface BrainstormReviewBackToChat {
  action: "back_to_chat";
}
export type BrainstormReviewResume = BrainstormReviewAdvance | BrainstormReviewBackToChat;

/** 构造「保存并推进」resume 值。power_system 仅在调用方判定 has_power_system=true 时传入。 */
export function buildBrainstormReviewAdvanceResume(fields: {
  core_theme: string;
  world_building: string;
  power_system?: string;
  core_conflicts: string;
}): BrainstormReviewAdvance {
  const out: BrainstormReviewAdvance = {
    action: "advance",
    core_theme: fields.core_theme.trim(),
    world_building: fields.world_building.trim(),
    core_conflicts: fields.core_conflicts.trim(),
  };
  if (fields.power_system !== undefined) out.power_system = fields.power_system.trim();
  return out;
}

/** 构造「返回脑爆继续修改」resume 值。 */
export function buildBrainstormReviewBackResume(): BrainstormReviewBackToChat {
  return { action: "back_to_chat" };
}
