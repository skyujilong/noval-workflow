// step_entry / arc_entry 的「跳过 / 执行」门表单。
// resume 值：""（skip 词）= 跳过；"yes"（非 skip 词）= 执行。

import { useEffect, useState } from "react";
import type { MessageOnlyPayload } from "../../lib/interruptTypes";
import { EXECUTE_VALUE, SKIP_VALUE } from "../../lib/interruptTypes";

interface Props {
  payload: MessageOnlyPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  title?: string;
  // 语义化按钮文案（默认「跳过」/「执行」）。resume 值不变：skip 按钮发 SKIP_VALUE、execute 按钮发 EXECUTE_VALUE。
  // 一致性总审复用本表单时传「通过冻结」/「重新审查」，语义映射：跳过=通过冻结、执行=重新审查。
  skipLabel?: string;
  executeLabel?: string;
}

export function EntryGateForm({
  payload,
  onSubmit,
  disabled,
  title,
  skipLabel = "跳过",
  executeLabel = "执行",
}: Props) {
  const [submitting, setSubmitting] = useState(false);

  // 提交结束或新 interrupt 时重置状态
  useEffect(() => {
    setSubmitting(false);
  }, [disabled, payload]);

  const handleSubmit = (value: string) => {
    setSubmitting(true);
    onSubmit(value);
  };

  // 本地 submitting 优先于上层 disabled，确保点击后立即禁用
  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        {title ?? "步骤确认"}
      </h3>
      <div className="whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
        {payload.message}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => handleSubmit(SKIP_VALUE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : skipLabel}
        </button>
        <button
          onClick={() => handleSubmit(EXECUTE_VALUE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : executeLabel}
        </button>
      </div>
    </div>
  );
}
