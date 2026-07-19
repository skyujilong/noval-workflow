// volume_cast（本卷花名册）专用可编辑审核表单——`review_type=volume_cast && threadId` 时替代只读卡片。
// 卷激活、展开 chapter_plan 之前，规划本卷登场阵容：
//   - introducing：本卷新登场重要人物/关键物品的**完整设定卡**（落 entity_cards canon）
//   - returning：本卷返场的已有角色 + 各自「本卷作用/弧线」（只引用名字，不重建卡）
//   - focus：本卷阵容主线一句话
//
// 数据通路（与 VolumesReviewForm 同款 update_state 覆写模式）：
//   1. 从 payload.current_draft 解析 {introducing, returning, focus} → 编辑态
//   2. 增删/编辑 introducing 卡（按 type 展示相关字段）+ returning 弧线 + focus
//   3. 「通过」→ updateThreadState 覆写 current_draft → onSubmit(approve resume)
//   4. 「提出修改意见」→ feedback 文本打回，AI 重生成
//
// 手改安全性：save_volume_cast 从 current_draft 解析后 introducing 走 merge_cards_from_json 去重
// 落库、returning/focus 落 volume_cast（覆盖语义）。前端不碰章号/卷号，那些由后端权威赋值。

import { useEffect, useMemo, useState } from "react";
import type { HumanReviewPayload, ReviewResume } from "../../lib/interruptTypes";
import { buildReviewResume } from "../../lib/interruptTypes";
import { updateThreadState } from "../../lib/langgraph";
import { ThinkingSwitch } from "./ThinkingSwitch";

interface Props {
  payload: HumanReviewPayload;
  onSubmit: (value: ReviewResume) => void;
  disabled?: boolean;
  threadId: string;
}

const ENTITY_TYPES = ["人物", "物品", "装备", "势力", "地点"] as const;
const CHARACTER_ROLES = [
  "主角",
  "主要配角",
  "功能性反派",
  "根源反派",
  "感情线角色",
  "次要角色",
] as const;

/** introducing 编辑态：宽松 key-value 卡（镜像后端 EntityCard 字段，parse_card 是字段权威）。 */
type CardDraft = Record<string, unknown>;
interface ReturningDraft {
  name: string;
  role_in_volume: string;
}
interface RosterDraft {
  introducing: CardDraft[];
  returning: ReturningDraft[];
  focus: string;
}

/** 字段配置：按 type 决定 introducing 卡展示哪些可编辑字段（textarea 用于长文本字段）。 */
const COMMON_FIELDS: { key: string; label: string; area?: boolean }[] = [
  { key: "summary", label: "一句话定位（≤30字）" },
];
const CHARACTER_FIELDS: { key: string; label: string; area?: boolean }[] = [
  { key: "appearance", label: "外貌基线", area: true },
  { key: "speech_style", label: "说话风格/口吻" },
  { key: "personality", label: "性格（表层）", area: true },
  { key: "abilities", label: "能力（落力量体系）", area: true },
  { key: "hidden_persona", label: "深层隐藏人设（仅主角/根源反派/关键反转角色）", area: true },
  { key: "arc_trajectory", label: "全书弧光（仅关键角色）", area: true },
  { key: "ability_contract", label: "能力底牌契约（仅战力关键角色）", area: true },
  { key: "motivation", label: "当前动机" },
  { key: "current_state", label: "当前处境" },
  { key: "relations", label: "与主角/他人关系", area: true },
];
const ITEM_FIELDS: { key: string; label: string; area?: boolean }[] = [
  { key: "owner", label: "归属人" },
  { key: "effect", label: "效果/能力", area: true },
  { key: "rank", label: "品阶/等级（落体系）" },
  { key: "status", label: "当前状态" },
];
const FACTION_FIELDS: { key: string; label: string; area?: boolean }[] = [
  { key: "standing", label: "当前强弱/格局" },
];

function fieldsForType(type: string) {
  if (type === "人物") return CHARACTER_FIELDS;
  if (type === "物品" || type === "装备") return ITEM_FIELDS;
  return FACTION_FIELDS; // 势力/地点
}

const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

function extractJson(raw: string): unknown | null {
  if (!raw || !raw.trim()) return null;
  const fenced = raw.trim().match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = (fenced ? fenced[1] : raw).trim();
  try {
    return JSON.parse(body);
  } catch {
    const start = body.indexOf("{");
    const end = body.lastIndexOf("}");
    if (start === -1 || end <= start) return null;
    try {
      return JSON.parse(body.slice(start, end + 1));
    } catch {
      return null;
    }
  }
}

/** 宽松解析花名册草稿 → RosterDraft；解析失败返回 null（走「提出修改意见」重生成）。 */
function tryParseRoster(raw: string): RosterDraft | null {
  const parsed = extractJson(raw);
  if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const o = parsed as Record<string, unknown>;
  const introducing = Array.isArray(o.introducing)
    ? (o.introducing.filter((c) => typeof c === "object" && c !== null) as CardDraft[])
    : [];
  const returning = Array.isArray(o.returning)
    ? (o.returning as unknown[])
        .map((r): ReturningDraft | null => {
          if (typeof r !== "object" || r === null) return null;
          const ro = r as Record<string, unknown>;
          return { name: str(ro.name), role_in_volume: str(ro.role_in_volume) };
        })
        .filter((r): r is ReturningDraft => r !== null)
    : [];
  return { introducing, returning, focus: str(o.focus) };
}

const emptyCard = (): CardDraft => ({ name: "", type: "人物", aliases: [], summary: "", role: "次要角色" });
const emptyReturning = (): ReturningDraft => ({ name: "", role_in_volume: "" });

/** 校验（阻断通过）：introducing 每张需 name+type，人物需 role；returning 每条需 name。 */
function validate(r: RosterDraft | null): string[] {
  if (!r) return ["未解析到有效的花名册 JSON（可提修改意见让 AI 重生成）"];
  const issues: string[] = [];
  r.introducing.forEach((c, i) => {
    if (!str(c.name).trim()) issues.push(`新登场卡 ${i + 1} 缺 名字`);
    if (!str(c.type).trim()) issues.push(`新登场卡 ${i + 1} 缺 类型`);
    if (str(c.type) === "人物" && !str(c.role).trim()) issues.push(`新登场人物「${str(c.name) || i + 1}」缺 角色定位(role)`);
  });
  r.returning.forEach((rr, i) => {
    if (!rr.name.trim()) issues.push(`返场角色 ${i + 1} 缺 名字`);
  });
  return issues;
}

const inputCls =
  "w-full rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100";

/** 单张 introducing 卡编辑块（按 type 展示相关字段）。 */
function CardEditor({
  card,
  disabled,
  onPatch,
  onRemove,
  index,
}: {
  card: CardDraft;
  disabled: boolean;
  onPatch: (p: CardDraft) => void;
  onRemove: () => void;
  index: number;
}) {
  const type = str(card.type) || "人物";
  const aliasesStr = Array.isArray(card.aliases) ? (card.aliases as unknown[]).map(str).join("、") : str(card.aliases);
  return (
    <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/40 px-3 py-3 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="rounded bg-emerald-600 px-2 py-0.5 text-[10px] font-medium text-white">
          新登场 {index + 1} · 完整设定卡
        </span>
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="text-[11px] text-red-500 hover:text-red-700 disabled:text-gray-300"
        >
          删除
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">名字</label>
          <input
            type="text"
            value={str(card.name)}
            onChange={(e) => onPatch({ ...card, name: e.target.value })}
            disabled={disabled}
            className={inputCls}
          />
        </div>
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">类型</label>
          <select
            value={type}
            onChange={(e) => onPatch({ ...card, type: e.target.value })}
            disabled={disabled}
            className={inputCls}
          >
            {ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="mb-0.5 block text-xs font-medium text-gray-500">别名（顿号/逗号分隔，无则留空）</label>
        <input
          type="text"
          value={aliasesStr}
          onChange={(e) =>
            onPatch({
              ...card,
              aliases: e.target.value
                .split(/[、,，]/)
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          disabled={disabled}
          className={inputCls}
        />
      </div>
      {type === "人物" && (
        <div>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">角色定位 (role)</label>
          <select
            value={str(card.role) || "次要角色"}
            onChange={(e) => onPatch({ ...card, role: e.target.value })}
            disabled={disabled}
            className={inputCls}
          >
            {CHARACTER_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      )}
      {[...COMMON_FIELDS, ...fieldsForType(type)].map((f) => (
        <div key={f.key}>
          <label className="mb-0.5 block text-xs font-medium text-gray-500">{f.label}</label>
          {f.area ? (
            <textarea
              value={str(card[f.key])}
              onChange={(e) => onPatch({ ...card, [f.key]: e.target.value })}
              disabled={disabled}
              rows={2}
              className={inputCls}
            />
          ) : (
            <input
              type="text"
              value={str(card[f.key])}
              onChange={(e) => onPatch({ ...card, [f.key]: e.target.value })}
              disabled={disabled}
              className={inputCls}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function VolumeCastReviewForm({ payload, onSubmit, disabled, threadId }: Props) {
  const aiFeedback = payload.review_feedback ?? "";
  const history = payload.review_history ?? [];
  const llmReviewCount = payload.llm_review_count ?? 0;
  const round = Math.floor((history.length || 0) / 2);

  const initial = useMemo(() => tryParseRoster(payload.current_draft ?? ""), [payload.current_draft]);

  const [roster, setRoster] = useState<RosterDraft | null>(initial);
  const [mode, setMode] = useState<"approve" | "revise">("approve");
  const [feedback, setFeedback] = useState("");
  const [thinkingOn, setThinkingOn] = useState(payload.default_thinking !== "disabled");
  const [submitting, setSubmitting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setSubmitting(false);
    setSaveError(null);
    setMode("approve");
    setFeedback("");
    setThinkingOn(payload.default_thinking !== "disabled");
    setRoster(tryParseRoster(payload.current_draft ?? ""));
  }, [payload, disabled]);

  const issues = useMemo(() => validate(roster), [roster]);

  const patchCard = (idx: number, next: CardDraft) =>
    setRoster((prev) =>
      prev ? { ...prev, introducing: prev.introducing.map((c, i) => (i === idx ? next : c)) } : prev,
    );
  const addCard = () =>
    setRoster((prev) => (prev ? { ...prev, introducing: [...prev.introducing, emptyCard()] } : prev));
  const removeCard = (idx: number) =>
    setRoster((prev) =>
      prev ? { ...prev, introducing: prev.introducing.filter((_, i) => i !== idx) } : prev,
    );
  const patchReturning = (idx: number, p: Partial<ReturningDraft>) =>
    setRoster((prev) =>
      prev
        ? { ...prev, returning: prev.returning.map((r, i) => (i === idx ? { ...r, ...p } : r)) }
        : prev,
    );
  const addReturning = () =>
    setRoster((prev) => (prev ? { ...prev, returning: [...prev.returning, emptyReturning()] } : prev));
  const removeReturning = (idx: number) =>
    setRoster((prev) =>
      prev ? { ...prev, returning: prev.returning.filter((_, i) => i !== idx) } : prev,
    );
  const setFocus = (v: string) => setRoster((prev) => (prev ? { ...prev, focus: v } : prev));

  const handleSubmit = async () => {
    if (mode === "approve" && (issues.length > 0 || !roster)) return;
    setSubmitting(true);
    setSaveError(null);

    if (mode === "approve" && roster) {
      // 覆写 current_draft 为花名册契约（human_confirmed 语义由后端 volume_cast 无需——introducing
      // 完整卡去重落库、returning/focus 落动态层，前端只保证结构合法）。
      const payloadObj = {
        introducing: roster.introducing,
        returning: roster.returning,
        focus: roster.focus,
      };
      try {
        await updateThreadState(threadId, { current_draft: JSON.stringify(payloadObj, null, 2) });
      } catch (e) {
        setSubmitting(false);
        setSaveError(`保存草稿失败：${(e as Error).message}`);
        return;
      }
    }

    onSubmit(buildReviewResume(mode === "approve" ? "" : feedback, thinkingOn));
  };

  const isDisabled = disabled || submitting;
  const canApprove = mode === "approve" && issues.length === 0 && roster != null;
  const canRevise = mode === "revise" && feedback.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">
          人工审核 · 本卷花名册
          {roster && (
            <span className="ml-2 text-xs font-normal text-gray-500">
              新登场 {roster.introducing.length} · 返场 {roster.returning.length}
            </span>
          )}
        </h3>
        {round > 0 && (
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            第 {round} 轮迭代（AI 自审 {llmReviewCount} 次）
          </span>
        )}
      </div>

      {aiFeedback && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="mb-1 text-xs font-medium text-amber-700">AI 自审意见</div>
          <div className="whitespace-pre-wrap text-sm text-amber-900">{aiFeedback}</div>
        </div>
      )}

      {saveError && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">⚠ {saveError}</div>
      )}

      {issues.length > 0 && (
        <ul className="space-y-0.5 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {issues.map((msg, i) => (
            <li key={i}>❌ {msg}</li>
          ))}
        </ul>
      )}

      {roster ? (
        <div className="space-y-4">
          {/* 本卷阵容主线 focus */}
          <div>
            <label className="mb-0.5 block text-xs font-medium text-gray-500">
              本卷阵容主线 (focus)：本卷谁挑大梁、核心看点
            </label>
            <textarea
              value={roster.focus}
              onChange={(e) => setFocus(e.target.value)}
              disabled={isDisabled}
              rows={2}
              className={inputCls}
            />
          </div>

          {/* 返场阵容 returning */}
          <div className="space-y-2">
            <div className="text-xs font-medium text-gray-600">本卷返场阵容（已有角色 + 各自本卷弧线）</div>
            {roster.returning.map((r, i) => (
              <div key={i} className="flex gap-2 rounded border border-gray-200 bg-white px-2 py-2">
                <input
                  type="text"
                  value={r.name}
                  onChange={(e) => patchReturning(i, { name: e.target.value })}
                  disabled={isDisabled}
                  placeholder="角色名"
                  className={inputCls + " w-32 flex-none"}
                />
                <input
                  type="text"
                  value={r.role_in_volume}
                  onChange={(e) => patchReturning(i, { role_in_volume: e.target.value })}
                  disabled={isDisabled}
                  placeholder="本卷作用/弧线（本卷做什么、与主线什么关系）"
                  className={inputCls}
                />
                <button
                  type="button"
                  onClick={() => removeReturning(i)}
                  disabled={isDisabled}
                  className="flex-none text-[11px] text-red-500 hover:text-red-700 disabled:text-gray-300"
                >
                  删除
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={addReturning}
              disabled={isDisabled}
              className="w-full rounded border border-dashed border-gray-300 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 disabled:text-gray-300"
            >
              + 添加返场角色
            </button>
          </div>

          {/* 新登场 introducing（完整设定卡）*/}
          <div className="space-y-2">
            <div className="text-xs font-medium text-gray-600">
              本卷新登场（完整设定卡，去重后并入实体卡库 canon）
            </div>
            {roster.introducing.map((c, i) => (
              <CardEditor
                key={i}
                card={c}
                index={i}
                disabled={isDisabled}
                onPatch={(next) => patchCard(i, next)}
                onRemove={() => removeCard(i)}
              />
            ))}
            <button
              type="button"
              onClick={addCard}
              disabled={isDisabled}
              className="w-full rounded border border-dashed border-emerald-300 px-3 py-2 text-xs text-emerald-600 hover:bg-emerald-50 disabled:text-gray-300"
            >
              + 添加新登场实体卡
            </button>
          </div>
        </div>
      ) : (
        <div className="rounded border border-dashed border-amber-300 bg-amber-50 px-3 py-4 text-center text-xs text-amber-700">
          未解析到有效的花名册 JSON（含 introducing/returning/focus）。请走「提出修改意见」让 AI 重新输出合规 JSON。
        </div>
      )}

      {/* 操作区 */}
      <div className="space-y-3 border-t pt-3">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("approve")}
            disabled={isDisabled}
            className={
              "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
              (mode === "approve"
                ? "border-green-600 bg-green-50 text-green-700"
                : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
            }
          >
            ✓ 通过（保存编辑并推进）
          </button>
          <button
            type="button"
            onClick={() => setMode("revise")}
            disabled={isDisabled}
            className={
              "flex-1 rounded border px-3 py-2 text-sm font-medium transition-colors " +
              (mode === "revise"
                ? "border-blue-600 bg-blue-50 text-blue-700"
                : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50")
            }
          >
            ✎ 提出修改意见（让 AI 重生成）
          </button>
        </div>

        {mode === "revise" && (
          <>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={isDisabled}
              placeholder="输入修改意见，AI 会据此重新生成本卷花名册（新登场卡 + 返场阵容 + 本卷主线）…"
              rows={4}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <ThinkingSwitch checked={thinkingOn} onChange={setThinkingOn} disabled={isDisabled} />
          </>
        )}

        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={isDisabled || (mode === "approve" ? !canApprove : !canRevise)}
          className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : mode === "approve" ? "确认通过" : "提交修改意见"}
        </button>

        {mode === "approve" && issues.length > 0 && (
          <div className="text-xs text-red-600">⚠ 存在 {issues.length} 项校验问题，请先修复再通过。</div>
        )}
      </div>
    </div>
  );
}
