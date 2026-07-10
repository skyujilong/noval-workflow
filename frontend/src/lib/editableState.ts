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

import type { ForeshadowingLedger, NovelState } from "./types";

// ── 字段定义 ─────────────────────────────────────────────────────────────────

/** 纯文本类可编辑字段（textarea 直接编辑） */
export type EditableTextKey =
  | "character_status"
  | "character_relations"
  | "phase_summary"
  | "current_arc_outline"
  | "core_theme"
  | "world_building"
  | "power_system"
  | "core_conflicts"
  | "overall_outline"
  | "character_profiles"
  | "current_draft";

/** 全部可编辑字段（含结构化的 foreshadowing） */
export type EditableStateKey = EditableTextKey | "foreshadowing";

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
  { key: "character_status", label: "人物动态状态", group: "snapshot", kind: "text" },
  { key: "character_relations", label: "人物关系 / 势力格局", group: "snapshot", kind: "text" },
  { key: "foreshadowing", label: "伏笔台账", group: "snapshot", kind: "ledger" },
  { key: "phase_summary", label: "阶段固化数据", group: "snapshot", kind: "text" },
  { key: "current_arc_outline", label: "当前弧线大纲", group: "snapshot", kind: "text" },
  { key: "core_theme", label: "核心主题", group: "foundation", kind: "text" },
  { key: "world_building", label: "世界观", group: "foundation", kind: "text" },
  { key: "power_system", label: "力量体系", group: "foundation", kind: "text" },
  { key: "core_conflicts", label: "核心冲突", group: "foundation", kind: "text" },
  { key: "overall_outline", label: "整体大纲", group: "foundation", kind: "text" },
  { key: "character_profiles", label: "人物档案", group: "foundation", kind: "text" },
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
