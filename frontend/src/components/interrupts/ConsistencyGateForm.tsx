// 设定一致性总审闸门：展示审计报告，三选——通过冻结 / 让 AI 修订 / 重新审查。
// resume 值为动作字符串（对齐后端 consistency_gate 的信号集）。
// 「让 AI 修订」仅在本轮发现问题（can_revise）时提供，且为主 CTA。

import { useEffect, useState } from "react";
import type { ConsistencyGatePayload } from "../../lib/interruptTypes";
import {
  CONSISTENCY_FREEZE,
  CONSISTENCY_REAUDIT,
  CONSISTENCY_REVISE,
} from "../../lib/interruptTypes";

interface Props {
  payload: ConsistencyGatePayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function ConsistencyGateForm({ payload, onSubmit, disabled }: Props) {
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setSubmitting(false);
  }, [disabled, payload]);

  const handleSubmit = (value: string) => {
    setSubmitting(true);
    onSubmit(value);
  };

  const isDisabled = disabled || submitting;
  const canRevise = payload.can_revise;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">设定一致性总审</h3>
      <div className="whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
        {payload.message}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => handleSubmit(CONSISTENCY_FREEZE)}
          disabled={isDisabled}
          className="flex-1 rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "通过冻结"}
        </button>
        {canRevise && (
          <button
            onClick={() => handleSubmit(CONSISTENCY_REVISE)}
            disabled={isDisabled}
            className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {submitting ? "⏳ 提交中..." : "让 AI 修订"}
          </button>
        )}
        <button
          onClick={() => handleSubmit(CONSISTENCY_REAUDIT)}
          disabled={isDisabled}
          className="flex-1 rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "重新审查"}
        </button>
      </div>
      {canRevise && (
        <p className="text-xs text-gray-400">
          「让 AI 修订」将由 AI 依据上述问题改写涉事设定，改动以 diff 呈现，可逐项编辑后应用。
        </p>
      )}
    </div>
  );
}
