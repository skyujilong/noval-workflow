// 一致性总审 · AI 修订 diff 审核：逐项展示 AI 改写的「改前 → 改后」高亮 diff，
// 每项可手动编辑修订后文本；应用则写回设定并自动复审一轮，放弃则不改动任何设定。
// resume 值：{action:"apply", revisions:[{field, after}]} 或 {action:"discard"}。

import { useEffect, useMemo, useState } from "react";
import type {
  ConsistencyDiffPayload,
  ConsistencyDiffResume,
} from "../../lib/interruptTypes";
import {
  buildConsistencyApplyResume,
  buildConsistencyDiscardResume,
} from "../../lib/interruptTypes";
import { TextDiff } from "./TextDiff";

interface Props {
  payload: ConsistencyDiffPayload;
  onSubmit: (value: ConsistencyDiffResume) => void;
  disabled?: boolean;
}

export function ConsistencyDiffForm({ payload, onSubmit, disabled }: Props) {
  const revisions = useMemo(() => payload.revisions ?? [], [payload]);
  // field → 当前（可编辑）修订后文本，初值取 AI 提案的 after。
  const [edited, setEdited] = useState<Record<string, string>>(() =>
    Object.fromEntries(revisions.map((r) => [r.field, r.after]))
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setSubmitting(false);
    setEdited(Object.fromEntries(revisions.map((r) => [r.field, r.after])));
  }, [disabled, payload, revisions]);

  const isDisabled = disabled || submitting;

  const handleApply = () => {
    setSubmitting(true);
    onSubmit(
      buildConsistencyApplyResume(
        revisions.map((r) => ({ field: r.field, after: edited[r.field] ?? "" }))
      )
    );
  };

  const handleDiscard = () => {
    setSubmitting(true);
    onSubmit(buildConsistencyDiscardResume());
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        AI 修订审核 · {revisions.length} 处改动
      </h3>
      <p className="text-sm text-gray-500">{payload.message}</p>

      <div className="space-y-4">
        {revisions.map((r) => (
          <div key={r.field} className="space-y-2 rounded border border-gray-200 p-3">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-gray-800">{r.label}</span>
              <span className="font-mono text-[10px] text-gray-400">{r.field}</span>
            </div>
            {r.reason && (
              <p className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
                修订理由：{r.reason}
              </p>
            )}
            <div>
              <div className="mb-1 text-[11px] text-gray-400">改动预览（改前 → 改后）</div>
              <TextDiff before={r.before} after={edited[r.field] ?? ""} />
            </div>
            <div>
              <div className="mb-1 text-[11px] text-gray-400">修订后（可编辑）</div>
              <textarea
                value={edited[r.field] ?? ""}
                onChange={(e) =>
                  setEdited((prev) => ({ ...prev, [r.field]: e.target.value }))
                }
                disabled={isDisabled}
                rows={8}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm leading-relaxed focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
              />
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleDiscard}
          disabled={isDisabled}
          className="flex-1 rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "放弃"}
        </button>
        <button
          type="button"
          onClick={handleApply}
          disabled={isDisabled}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : "应用修订并复审"}
        </button>
      </div>
    </div>
  );
}
