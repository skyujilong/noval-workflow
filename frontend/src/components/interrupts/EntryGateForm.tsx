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
}

export function EntryGateForm({ payload, onSubmit, disabled, title }: Props) {
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
          {submitting ? "⏳" : "跳过"}
        </button>
        <button
          onClick={() => handleSubmit(EXECUTE_VALUE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : "执行"}
        </button>
      </div>
    </div>
  );
}
