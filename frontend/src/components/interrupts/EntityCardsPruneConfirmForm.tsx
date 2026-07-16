// 实体卡库精简确认表单：展示**全部**卡（按类型分组），AI 建议删除的默认预选并标注理由，
// 用户可自行增减后确认整卡删除。与伏笔精简同构，但列出全库而非只列建议删的。
// resume 值：选中删除的实体名 JSON 字符串数组，如 ["张三","遣散费"]；空数组表示不删除。

import { useEffect, useMemo, useState } from "react";
import type { EntityCardsPruneConfirmPayload } from "../../lib/interruptTypes";

interface Props {
  payload: EntityCardsPruneConfirmPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

// 分组展示顺序 + 类型徽标配色（与 EntityCardsReadonly 口径一致）。
const TYPE_ORDER = ["人物", "装备", "物品", "势力", "地点"] as const;
const TYPE_BADGE: Record<string, string> = {
  人物: "border-indigo-200 bg-indigo-50 text-indigo-700",
  装备: "border-amber-200 bg-amber-50 text-amber-700",
  物品: "border-emerald-200 bg-emerald-50 text-emerald-700",
  势力: "border-rose-200 bg-rose-50 text-rose-700",
  地点: "border-sky-200 bg-sky-50 text-sky-700",
};

export function EntityCardsPruneConfirmForm({ payload, onSubmit, disabled }: Props) {
  const cards = payload.cards ?? [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  // 默认预选 AI 建议删除的卡（suggested=true）
  useEffect(() => {
    setSelected(new Set(cards.filter((c) => c.suggested).map((c) => c.name)));
  }, [payload]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!disabled) setSubmitting(false);
  }, [disabled]);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // 已知类型按 TYPE_ORDER 分组，其余归「其他」，稳序展示。
  const groups = useMemo(() => {
    const known = TYPE_ORDER.map((t) => ({ label: t as string, items: cards.filter((c) => c.type === t) }));
    const others = cards.filter((c) => !TYPE_ORDER.includes(c.type as (typeof TYPE_ORDER)[number]));
    if (others.length > 0) known.push({ label: "其他", items: others });
    return known.filter((g) => g.items.length > 0);
  }, [cards]);

  const resetToSuggested = () => {
    setSelected(new Set(cards.filter((c) => c.suggested).map((c) => c.name)));
  };
  const clearAll = () => setSelected(new Set());

  const handleConfirm = () => {
    setSubmitting(true);
    onSubmit(JSON.stringify(Array.from(selected)));
  };
  const handleSkip = () => {
    setSubmitting(true);
    onSubmit("[]");
  };

  const isDisabled = disabled || submitting;
  const remaining = cards.length - selected.size;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">实体卡库精简</h3>
        <div className="flex items-center gap-3 text-xs">
          <button
            type="button"
            onClick={resetToSuggested}
            disabled={isDisabled}
            className="text-blue-600 hover:text-blue-800 disabled:text-gray-400"
          >
            按 AI 建议
          </button>
          <button
            type="button"
            onClick={clearAll}
            disabled={isDisabled}
            className="text-gray-500 hover:text-gray-700 disabled:text-gray-300"
          >
            全不选
          </button>
        </div>
      </div>

      {/* 概览：全库张数 / AI 建议删 / 已选删 */}
      <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-gray-700">
        卡库共 <span className="font-semibold text-gray-800">{payload.total_count}</span> 张 ·
        AI 建议删除 <span className="font-semibold text-rose-600">{payload.suggested_count}</span> 张 ·
        当前已选删 <span className="font-semibold text-rose-600">{selected.size}</span> 张 ·
        精简后剩 <span className="font-semibold text-green-600">{Math.max(0, remaining)}</span> 张
      </div>

      <p className="text-sm text-gray-500">
        已预选 AI 建议删除的卡（🗑️ 标注理由）。可勾选其他一次性碎屑 / 彻底离场且不再复现的卡一并删除，
        重要角色即便离场也建议保留（可能回忆 / 复活 / 遗泽影响剧情）。
      </p>

      {groups.map((g) => (
        <div key={g.label} className="rounded border border-gray-200 bg-white p-3">
          <h4 className="mb-2 text-sm font-medium text-gray-700">
            {g.label}（{g.items.length}）
          </h4>
          <div className="space-y-2">
            {g.items.map((c) => {
              const checked = selected.has(c.name);
              return (
                <label
                  key={c.name}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                    checked
                      ? "border-rose-200 bg-rose-50 hover:bg-rose-100"
                      : "border-gray-200 bg-gray-50 hover:bg-gray-100"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(c.name)}
                    disabled={isDisabled}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-rose-600 focus:ring-rose-500"
                  />
                  <div className="flex-1 text-sm">
                    <div className="mb-0.5 flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-gray-800">{c.name}</span>
                      {c.role && (
                        <span className="rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] leading-none text-indigo-700">
                          {c.role}
                        </span>
                      )}
                      <span
                        className={`rounded border px-1.5 py-0.5 text-[10px] leading-none ${
                          TYPE_BADGE[c.type] ?? "border-gray-200 bg-gray-50 text-gray-600"
                        }`}
                      >
                        {c.type || "未分类"}
                      </span>
                      {c.suggested && (
                        <span className="rounded border border-rose-200 bg-white px-1.5 py-0.5 text-[10px] leading-none text-rose-600">
                          🗑️ AI 建议删除
                        </span>
                      )}
                      {c.first_appear_chapter ? (
                        <span className="text-[10px] text-gray-400">首登 · 第 {c.first_appear_chapter} 章</span>
                      ) : null}
                    </div>
                    {c.summary && <div className="text-gray-500">定位 · {c.summary}</div>}
                    {c.current_state && <div className="text-gray-500">处境 · {c.current_state}</div>}
                    {c.suggested && c.reason && (
                      <div className="mt-0.5 text-rose-500">
                        <span className="text-rose-400">建议理由：</span>
                        {c.reason}
                      </div>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      ))}

      {cards.length === 0 && (
        <div className="rounded border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
          卡库为空，无需精简。
        </div>
      )}

      {/* 整体建议 */}
      {payload.suggestion && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="text-sm text-amber-800">💡 {payload.suggestion}</div>
        </div>
      )}

      {/* 操作区 */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={handleSkip}
          disabled={isDisabled}
          className="flex-1 rounded border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
        >
          {submitting ? "⏳ 处理中..." : "跳过，不删除"}
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={isDisabled || selected.size === 0}
          className="flex-1 rounded bg-rose-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {submitting ? "⏳ 处理中..." : `确认精简（删除 ${selected.size} 张）`}
        </button>
      </div>
    </div>
  );
}
