// 脑爆入口门：选「进入灵感脑爆」或「直接填表」。
// resume 值：BRAINSTORM_ENTER = 进脑爆；BRAINSTORM_DIRECT = 走常规流程。

import { useEffect, useState } from "react";
import type { MessageOnlyPayload } from "../../lib/interruptTypes";
import { BRAINSTORM_DIRECT, BRAINSTORM_ENTER } from "../../lib/interruptTypes";

interface Props {
  payload: MessageOnlyPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function BrainstormGateForm({ payload, onSubmit, disabled }: Props) {
  const [submitting, setSubmitting] = useState(false);

  // 提交结束或新 interrupt 时重置
  useEffect(() => {
    setSubmitting(false);
  }, [disabled, payload]);

  const handleSubmit = (value: string) => {
    setSubmitting(true);
    onSubmit(value);
  };

  // 本地 submitting 优先于上层 disabled，点击后立即禁用
  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">开始之前</h3>
      <div className="whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
        {payload.message}
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => handleSubmit(BRAINSTORM_DIRECT)}
          disabled={isDisabled}
          className="flex-1 rounded bg-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "直接填表"}
        </button>
        <button
          type="button"
          onClick={() => handleSubmit(BRAINSTORM_ENTER)}
          disabled={isDisabled}
          className="flex-1 rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 进入中..." : "✨ 进入灵感脑爆"}
        </button>
      </div>
    </div>
  );
}
