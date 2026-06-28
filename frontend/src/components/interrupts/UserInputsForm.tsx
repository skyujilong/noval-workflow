// collect_user_inputs 的结构化表单。
// payload 含 fields（字段名→说明）与 current_values（预填值）。
// resume 值：dict {字段名: 值}。

import { useEffect, useState } from "react";
import type { UserInputsPayload } from "../../lib/interruptTypes";
import { GENRE_OPTIONS } from "../../constants/genreOptions";

interface Props {
  payload: UserInputsPayload;
  onSubmit: (value: Record<string, string>) => void;
  disabled?: boolean;
}

const FIELD_LABELS: Record<string, string> = {
  novel_name: "小说名称",
  genre: "小说类型",
  writing_style: "写作风格",
  target_audience: "目标读者",
  core_tone: "核心基调",
  chapter_word_count: "每章字数",
  total_word_count: "总字数目标",
};

export function UserInputsForm({ payload, onSubmit, disabled }: Props) {
  const fieldNames = Object.keys(payload.fields ?? {});
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const k of fieldNames) init[k] = payload.current_values?.[k] ?? "";
    return init;
  });
  const [submitting, setSubmitting] = useState(false);

  // 提交结束（disabled false）或新 interrupt（payload 变化）时重置状态
  useEffect(() => {
    setSubmitting(false);
    const init: Record<string, string> = {};
    const names = Object.keys(payload.fields ?? {});
    for (const k of names) init[k] = payload.current_values?.[k] ?? "";
    setValues(init);
  }, [disabled, payload]);

  const handleSubmit = () => {
    setSubmitting(true);
    const result: Record<string, string> = {};
    for (const k of fieldNames) result[k] = values[k]?.trim() ?? "";
    onSubmit(result);
  };

  // 本地 submitting 优先于上层 disabled，确保点击后立即禁用所有控件
  const isDisabled = disabled || submitting;

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">小说创作参数</h3>
      <p className="text-sm text-gray-500">{payload.message}</p>
      <div className="space-y-3">
        {fieldNames.map((k) => (
          <div key={k}>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {FIELD_LABELS[k] ?? k}
              <span className="ml-2 text-xs text-gray-400 font-normal">
                {payload.fields[k]}
              </span>
            </label>
            {k === "genre" ? (
              <select
                value={values[k] ?? ""}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                disabled={isDisabled}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
              >
                <option value="">请选择小说类型</option>
                {GENRE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={values[k] ?? ""}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                disabled={isDisabled}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
              />
            )}
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={handleSubmit}
        disabled={isDisabled || fieldNames.some((k) => !values[k]?.trim())}
        className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        {submitting ? "⏳ 提交中..." : "提交并开始创作"}
      </button>
    </div>
  );
}
