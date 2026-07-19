// 「就地编辑当前 state」的可编辑字段白名单与工具。
//
// 只暴露安全可覆盖的字段（均为 last-value-wins，无 reducer）。刻意排除：
//   - reducer 字段 all_chapter_titles / all_chapter_summaries（operator.add → update 是追加不是覆盖）
//   - 进度/计数 current_chapter_index / total_chapters_written / current_batch_titles / continue_writing
//   - 桥接/控制 approved / review_feedback / review_type / llm_review_count / system_context / task_prompt
//   - 基础输入 novel_name / genre 等（几乎不需改，误改影响提示词包/文件路径）
//
// foreshadowing（伏笔台账）是结构化 dict，见 src/novel_workflow/prompts/ledger.py：
//   { "pending": [entry...], "collected": [entry...] }，故用结构化编辑器而非手写 JSON。

import type { EntityCard, ForeshadowingLedger, NovelState, Volume } from "./types";

// ── 字段定义 ─────────────────────────────────────────────────────────────────

/** 纯文本类可编辑字段（textarea 直接编辑）。
 *  人物档案不再是可整段编辑的散文字段——已并入结构化卡库 entity_cards，改动走 EntityCardsEditor。 */
export type EditableTextKey =
  | "phase_summary"
  | "current_arc_outline"
  | "core_theme"
  | "world_building"
  | "power_system"
  | "core_conflicts"
  | "overall_outline"
  | "current_draft";

/** 结构化 JSON 类可编辑字段（源码编辑 + 解析校验，非白名单文本）。 */
export type EditableJsonKey = "entity_cards" | "volumes";

/** 全部可编辑字段（含结构化的 foreshadowing 与 JSON 类 entity_cards） */
export type EditableStateKey = EditableTextKey | "foreshadowing" | EditableJsonKey;

export type EditableGroup = "snapshot" | "foundation" | "draft";

export interface EditableFieldDef {
  key: EditableStateKey;
  label: string;
  group: EditableGroup;
  /** text = textarea；ledger = 伏笔台账结构化编辑器 */
  kind: "text" | "ledger";
}

export const EDITABLE_GROUP_LABELS: Record<EditableGroup, string> = {
  snapshot: "动态状态库 · 快照台账",
  foundation: "基础设定",
  draft: "当前草稿",
};

export const EDITABLE_GROUP_ORDER: EditableGroup[] = ["snapshot", "foundation", "draft"];

export const EDITABLE_FIELDS: EditableFieldDef[] = [
  { key: "foreshadowing", label: "伏笔台账", group: "snapshot", kind: "ledger" },
  { key: "phase_summary", label: "阶段固化数据", group: "snapshot", kind: "text" },
  { key: "current_arc_outline", label: "当前弧线大纲", group: "snapshot", kind: "text" },
  { key: "core_theme", label: "核心主题", group: "foundation", kind: "text" },
  { key: "world_building", label: "世界观", group: "foundation", kind: "text" },
  { key: "power_system", label: "力量体系", group: "foundation", kind: "text" },
  { key: "core_conflicts", label: "核心冲突", group: "foundation", kind: "text" },
  { key: "overall_outline", label: "整体大纲", group: "foundation", kind: "text" },
  // 人物档案不在此列——它现在是结构化卡库，走 entity_cards（EntityCardsEditor）编辑
  { key: "current_draft", label: "当前草稿", group: "draft", kind: "text" },
];

/** 只提交改动字段的 patch（foreshadowing 为对象/字符串，其余为字符串）。 */
export type EditableStatePatch = Partial<Pick<NovelState, EditableStateKey>>;

// ── 文本字段草稿 ──────────────────────────────────────────────────────────────

export type TextDraft = Record<EditableTextKey, string>;

export function buildTextDraft(state: NovelState): TextDraft {
  const draft = {} as TextDraft;
  for (const f of EDITABLE_FIELDS) {
    if (f.kind === "text") {
      const key = f.key as EditableTextKey;
      draft[key] = (state[key] as string) ?? "";
    }
  }
  return draft;
}

export function diffTextKeys(draft: TextDraft, baseline: TextDraft): EditableTextKey[] {
  return (Object.keys(draft) as EditableTextKey[]).filter((k) => draft[k] !== baseline[k]);
}

// ── 伏笔台账（结构化）────────────────────────────────────────────────────────

export interface ForeshadowingEntry {
  id: string; // 伏笔编号，如 F01
  name: string; // 伏笔名称
  planted_batch: number; // 埋点批次
  current_appearance: string; // 当前潜伏表现
  core_purpose: string; // 核心作用
  planned_recovery_range: string; // 预定回收区间
  freedom: string; // 自由度：高/中/低
  recovered_at_chapter?: number; // 仅已收：回收章节
}

export interface ForeshadowingLedgerObj {
  pending: ForeshadowingEntry[];
  collected: ForeshadowingEntry[];
}

export const FREEDOM_OPTIONS = ["高", "中", "低"] as const;

export function emptyLedger(): ForeshadowingLedgerObj {
  return { pending: [], collected: [] };
}

export function newForeshadowingEntry(): ForeshadowingEntry {
  return {
    id: "",
    name: "",
    planted_batch: 0,
    current_appearance: "",
    core_purpose: "",
    planned_recovery_range: "",
    freedom: "中",
  };
}

/** 字段顺序固定，保证结构相等的两个台账 JSON.stringify 一致（供 dirty 比较）。 */
function coerceEntry(raw: unknown): ForeshadowingEntry {
  const o = (raw ?? {}) as Record<string, unknown>;
  const entry: ForeshadowingEntry = {
    id: String(o.id ?? ""),
    name: String(o.name ?? ""),
    planted_batch: Number(o.planted_batch ?? 0) || 0,
    current_appearance: String(o.current_appearance ?? ""),
    core_purpose: String(o.core_purpose ?? ""),
    planned_recovery_range: String(o.planned_recovery_range ?? ""),
    freedom: String(o.freedom ?? "中"),
  };
  if (o.recovered_at_chapter != null) {
    entry.recovered_at_chapter = Number(o.recovered_at_chapter) || 0;
  }
  return entry;
}

/**
 * 台账草稿：结构化（新格式 dict）或旧版纯文本（历史遗留的【】文本，未迁移过）。
 * 旧版走原文 textarea 兜底，避免结构化解析丢数据；新格式走结构化编辑器。
 */
export type LedgerDraft =
  | { mode: "structured"; value: ForeshadowingLedgerObj }
  | { mode: "legacy"; text: string };

export function toLedgerDraft(value: ForeshadowingLedger | undefined): LedgerDraft {
  if (value == null) return { mode: "structured", value: emptyLedger() };
  if (typeof value === "string") {
    return value.trim()
      ? { mode: "legacy", text: value }
      : { mode: "structured", value: emptyLedger() };
  }
  const o = value as Record<string, unknown>;
  return {
    mode: "structured",
    value: {
      pending: Array.isArray(o.pending) ? o.pending.map(coerceEntry) : [],
      collected: Array.isArray(o.collected) ? o.collected.map(coerceEntry) : [],
    },
  };
}

/** 草稿 → 提交值（结构化返回对象，旧版返回字符串）。 */
export function ledgerDraftValue(d: LedgerDraft): ForeshadowingLedger {
  if (d.mode === "legacy") return d.text;
  // ForeshadowingLedgerObj 是合法台账值，仅因缺少索引签名不被判为 Record<string, unknown>；
  // 语义上等价，显式转换。
  return d.value as unknown as ForeshadowingLedger;
}

export function ledgerDraftEqual(a: LedgerDraft, b: LedgerDraft): boolean {
  if (a.mode !== b.mode) return false;
  if (a.mode === "legacy" && b.mode === "legacy") return a.text === b.text;
  if (a.mode === "structured" && b.mode === "structured") {
    return JSON.stringify(a.value) === JSON.stringify(b.value);
  }
  return false;
}

// ── 登场实体卡（entity_cards，结构化 JSON 源码编辑）────────────────────────────
//
// entity_cards 是 list[EntityCard]，字段多且含 type 条件字段，故用「JSON 源码编辑 + 解析
// 校验」而非逐字段表单：手写 JSON 直观、可批量改。校验规则与后端 EntityCard 对齐
// （见 state.py::EntityCard / nodes/entity_cards.py::_coerce_card）——name/type 必填、
// type 枚举合法、aliases 为字符串数组、其余字段类型正确，任一不合格禁止保存（fail-fast，
// 避免脏数据经 update_state 覆盖进卡库后在下游 _coerce_card 处炸）。
//
// 手改安全性：卡库是覆盖语义（无 reducer），且章前 _merge_cards 对已有卡 canon 锁定只 append、
// 章末 _apply_updates 只改 status/owner/motivation——手改的核心字段不会被后续章节冲掉。

/** 合法 type 枚举，与 prompts/entity_cards.py::ENTITY_TYPES / state.EntityCard.type 同步。 */
export const ENTITY_CARD_TYPES = ["人物", "物品", "装备", "势力", "地点"];

/** 人物 role 六枚举，与后端 state.CharacterRole 同步（供实体卡编辑表单的 role 下拉）。
 * 注意：这与 langgraph.PROMOTABLE_ROLES（4 值，次要角色→重要角色的可提升目标）不同——
 * 这里是「手改任意人物卡 role」的全集，含主角/次要角色。 */
export const CHARACTER_ROLES = [
  "主角",
  "主要配角",
  "功能性反派",
  "根源反派",
  "感情线角色",
  "次要角色",
] as const;

/** EntityCard 里的字符串型可选字段（校验时逐一核对类型）。与后端判别联合字段并集对齐。 */
const ENTITY_CARD_STRING_FIELDS = [
  "summary",
  // 人物段
  "role",
  "appearance",
  "speech_style",
  "personality",
  "abilities",
  "hidden_persona",
  "arc_trajectory",
  "ability_contract",
  "motivation",
  "current_state",
  "relations",
  // 物品/装备段
  "owner",
  "effect",
  "status",
  "rank",
  // 势力/地点段
  "standing",
];

/** 把卡库序列化成缩进 JSON 源码（编辑器初值）。 */
export function buildEntityCardsJson(state: NovelState): string {
  return JSON.stringify(state.entity_cards ?? [], null, 2);
}

export interface EntityCardsParse {
  ok: boolean;
  value?: EntityCard[];
  /** 校验失败的具体原因（定位到第几张卡 + 字段），供编辑器 inline 提示。 */
  error?: string;
}

/**
 * 解析并校验实体卡 JSON 源码。空串视为「清空卡库」（合法，返回空数组）。
 * 校验对齐后端 EntityCard：name/type 必填、type 枚举、aliases 字符串数组、
 * first_appear_chapter 数字、其余字符串字段类型正确。任一不合格返回 {ok:false,error}。
 */
export function parseEntityCardsJson(text: string): EntityCardsParse {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: [] };

  let raw: unknown;
  try {
    raw = JSON.parse(trimmed);
  } catch (e) {
    return { ok: false, error: `JSON 语法错误：${(e as Error).message}` };
  }
  if (!Array.isArray(raw)) {
    return { ok: false, error: "顶层必须是数组 [ ... ]（每个元素是一张实体卡）" };
  }

  for (let i = 0; i < raw.length; i++) {
    const at = `第 ${i + 1} 张卡`;
    const o = raw[i];
    if (typeof o !== "object" || o === null || Array.isArray(o)) {
      return { ok: false, error: `${at}不是对象 { ... }` };
    }
    const rec = o as Record<string, unknown>;
    const name = rec.name;
    if (typeof name !== "string" || !name.trim()) {
      return { ok: false, error: `${at}缺 name（实体名，必填非空）` };
    }
    const type = rec.type;
    if (typeof type !== "string" || !ENTITY_CARD_TYPES.includes(type)) {
      return {
        ok: false,
        error: `${at}「${name}」type 非法（须为 ${ENTITY_CARD_TYPES.join("/")} 之一）`,
      };
    }
    if (rec.aliases !== undefined) {
      if (!Array.isArray(rec.aliases) || rec.aliases.some((a) => typeof a !== "string")) {
        return { ok: false, error: `${at}「${name}」aliases 必须是字符串数组` };
      }
    }
    if (rec.first_appear_chapter !== undefined && typeof rec.first_appear_chapter !== "number") {
      return { ok: false, error: `${at}「${name}」first_appear_chapter 必须是数字` };
    }
    for (const f of ENTITY_CARD_STRING_FIELDS) {
      if (rec[f] !== undefined && typeof rec[f] !== "string") {
        return { ok: false, error: `${at}「${name}」${f} 必须是字符串` };
      }
    }
  }
  return { ok: true, value: raw as EntityCard[] };
}

/**
 * 比较两份卡库 JSON 源码是否等价（供 dirty 判定）。两边都合法则按解析后的值比较
 * （忽略缩进/空白/字段顺序差异，避免纯格式化被误判为已改）；任一非法则退化为文本比较。
 */
export function entityCardsJsonEqual(a: string, b: string): boolean {
  const pa = parseEntityCardsJson(a);
  const pb = parseEntityCardsJson(b);
  if (pa.ok && pb.ok) return JSON.stringify(pa.value) === JSON.stringify(pb.value);
  return a === b;
}

// ── 分卷规划（volumes，结构化 JSON 源码编辑）──────────────────────────────────
//
// volumes 是 list[Volume]（滚动生成卷架构），字段固定 + 章号硬约束（chapter_start 顺次拼接
// = 上一卷 planned_end + 1、planned_end >= chapter_start、actual_end 可 null）。因数据量小、
// 校验规则明确，走「JSON 源码 + 解析校验」路径，与 entity_cards 同构。校验对齐后端 Volume——
// 任一不合格禁止保存，避免脏数据经 update_state 覆盖后在 volume_position_card 处炸。
//
// 允许字段：index/title/summary/setup_for_next/chapter_start/planned_end/actual_end/status
// （target_min/target_max 过渡期仍接受但不强校验，Step 5 删）。
// 手改安全性：volumes 覆盖语义（无 reducer），除非滚动生成卷分支才被程序覆盖。

const VOLUME_STATUS_VALUES = ["planning", "in_progress", "closed"] as const;
const VOLUME_STRING_FIELDS = ["title", "summary", "setup_for_next"] as const;
const VOLUME_INT_FIELDS = ["index", "chapter_start", "planned_end"] as const;
const VOLUME_ALLOWED_KEYS = new Set<string>([
  "index",
  "title",
  "summary",
  "setup_for_next",
  "chapter_start",
  "planned_end",
  "target_min", // 过渡期遗留，接受但不强校验（Step 5 删）
  "target_max", // 过渡期遗留
  "actual_end",
  "status",
]);

/** 把分卷列表序列化成缩进 JSON 源码（编辑器初值）。 */
export function buildVolumesJson(state: NovelState): string {
  return JSON.stringify(state.volumes ?? [], null, 2);
}

export interface VolumesParse {
  ok: boolean;
  value?: Volume[];
  /** 校验失败原因（定位到第几卷 + 字段），供编辑器 inline 提示。 */
  error?: string;
}

/**
 * 解析并校验分卷 JSON 源码。空串视为「清空 volumes」（合法，返回空数组=禁用分卷特性）。
 * 对齐后端 Volume（滚动生成卷架构）：
 *   - 顶层必须是数组
 *   - 每项字段严格在白名单内（额外字段直接拒绝）
 *   - index 从 1 严格顺次
 *   - planned_end >= chapter_start（本卷至少 1 章）
 *   - chapter_start 顺次拼接：chapter_start[i+1] = 上一卷 planned_end + 1
 *   - status 必须是 planning/in_progress/closed
 *   - actual_end 允许 null 或正整数
 */
export function parseVolumesJson(text: string): VolumesParse {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: [] };

  let raw: unknown;
  try {
    raw = JSON.parse(trimmed);
  } catch (e) {
    return { ok: false, error: `JSON 语法错误：${(e as Error).message}` };
  }
  if (!Array.isArray(raw)) {
    return { ok: false, error: "顶层必须是数组 [ ... ]（每个元素是一卷）" };
  }

  const volumes: Volume[] = [];
  let nextExpectedStart = 1;
  for (let i = 0; i < raw.length; i++) {
    const at = `第 ${i + 1} 卷`;
    const o = raw[i];
    if (typeof o !== "object" || o === null || Array.isArray(o)) {
      return { ok: false, error: `${at}不是对象 { ... }` };
    }
    const rec = o as Record<string, unknown>;

    // 白名单外的字段直接拒绝（对齐 Volume(**item) 的 TypeError 语义）
    for (const key of Object.keys(rec)) {
      if (!VOLUME_ALLOWED_KEYS.has(key)) {
        return { ok: false, error: `${at}含未知字段「${key}」（Volume 只支持 9 个字段）` };
      }
    }

    // int 字段：必填且必须是整数
    for (const f of VOLUME_INT_FIELDS) {
      if (typeof rec[f] !== "number" || !Number.isInteger(rec[f])) {
        return { ok: false, error: `${at} ${f} 必须是整数` };
      }
    }
    const index = rec.index as number;
    const chapter_start = rec.chapter_start as number;
    const planned_end = rec.planned_end as number;
    // 过渡期遗留字段：接受但不强校验（滚动架构下恒为 0）
    const target_min = typeof rec.target_min === "number" ? (rec.target_min as number) : 0;
    const target_max = typeof rec.target_max === "number" ? (rec.target_max as number) : 0;

    // string 字段：必填（可空串）、必须是字符串
    for (const f of VOLUME_STRING_FIELDS) {
      if (typeof rec[f] !== "string") {
        return { ok: false, error: `${at} ${f} 必须是字符串（可为空串）` };
      }
    }
    const title = rec.title as string;
    const summary = rec.summary as string;
    const setup_for_next = rec.setup_for_next as string;

    // actual_end: 允许 null 或正整数
    let actual_end: number | null = null;
    if (rec.actual_end !== undefined && rec.actual_end !== null) {
      if (typeof rec.actual_end !== "number" || !Number.isInteger(rec.actual_end) || rec.actual_end <= 0) {
        return { ok: false, error: `${at} actual_end 必须是正整数或 null` };
      }
      actual_end = rec.actual_end;
    }

    // status: 必填枚举
    const status = rec.status;
    if (typeof status !== "string" || !VOLUME_STATUS_VALUES.includes(status as Volume["status"])) {
      return { ok: false, error: `${at} status 必须是 ${VOLUME_STATUS_VALUES.join("/")} 之一` };
    }

    // 拼接规则 + 章号合法性（planned_end 权威）
    if (index !== i + 1) {
      return { ok: false, error: `${at} index=${index}，应为 ${i + 1}（1-based 严格顺次）` };
    }
    if (chapter_start !== nextExpectedStart) {
      return {
        ok: false,
        error: `${at} chapter_start=${chapter_start}，应为 ${nextExpectedStart}（拼接规则：chapter_start[i+1] = 上一卷 planned_end + 1）`,
      };
    }
    if (planned_end < chapter_start) {
      return {
        ok: false,
        error: `${at} planned_end=${planned_end} 必须 ≥ chapter_start=${chapter_start}（本卷至少 1 章）`,
      };
    }

    volumes.push({
      index,
      title,
      summary,
      setup_for_next,
      chapter_start,
      planned_end,
      target_min,
      target_max,
      actual_end,
      status: status as Volume["status"],
    });
    nextExpectedStart = planned_end + 1;
  }
  return { ok: true, value: volumes };
}

/** 分卷 JSON 源码等价比较：合法则解析后比对（忽略格式化），非法退化为文本比较。 */
export function volumesJsonEqual(a: string, b: string): boolean {
  const pa = parseVolumesJson(a);
  const pb = parseVolumesJson(b);
  if (pa.ok && pb.ok) return JSON.stringify(pa.value) === JSON.stringify(pb.value);
  return a === b;
}
