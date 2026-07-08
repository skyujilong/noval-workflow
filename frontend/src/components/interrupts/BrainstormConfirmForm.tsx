// 脑爆产物轻量确认（core_theme / world_building）：展示脑爆生成的内容，
// 用户可直接编辑后确认。不会触发重新生成、不冲洗。
// resume 值：编辑后的终稿文本（与原文相同即等于「直接确认」）。

import { useEffect, useState } from "react";
import type { BrainstormConfirmPayload } from "../../lib/interruptTypes";

interface Props {
  payload: BrainstormConfirmPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function BrainstormConfirmForm({ payload, onSubmit, disabled }: Props) {
  const content = payload.content ?? "";
  const [text, setText] = useState(content);
  const [submitting, setSubmitting] = useState(false);

  // 新 interrupt（payload 变化）或提交结束时，把编辑框重置回最新内容
  useEffect(() => {
    setSubmitting(false);
    setText(payload.content ?? "");
  }, [disabled, payload]);

  const handleSubmit = () => {
    setSubmitting(true);
    onSubmit(text.trim());
  };

  // 本地 submitting 优先于上层 disabled，点击后立即禁用
  const isDisabled = disabled || submitting;
  const edited = text.trim() !== content.trim();
  const title = payload.title?.trim();

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        {title ? `脑爆产物确认 · ${title}` : "脑爆产物确认"}
      </h3>
      <p className="text-sm text-gray-500">{payload.message}</p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={isDisabled}
        rows={14}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm leading-relaxed focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={isDisabled || !text.trim()}
        className="w-full rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        {submitting ? "⏳ 提交中..." : edited ? "保存修改并继续" : "确认并继续"}
      </button>
    </div>
  );
}
