// step_direction / arc_direction 的方向输入表单。
// resume 值："" = 用默认 / 取消；非空 = 调整方向。
// arc_direction 的 payload 含 current_arc_outline / remaining_titles，额外展示上下文。

import { useEffect, useState } from "react";
import type { ArcDirectionPayload, MessageOnlyPayload } from "../../lib/interruptTypes";
import { directionTitleOf } from "../../lib/interruptTypes";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  payload: MessageOnlyPayload | ArcDirectionPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function DirectionForm({ payload, onSubmit, disabled }: Props) {
  const [direction, setDirection] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const arc = (payload as ArcDirectionPayload).current_arc_outline ?? "";
  const remaining = (payload as ArcDirectionPayload).remaining_titles ?? [];
  // 标题由 payload.type 派生（type 自描述契约），无需外部传入
  const title = directionTitleOf((payload as { type?: unknown }).type);

  // 提交结束（disabled false）或新 interrupt（payload 变化）时重置状态
  useEffect(() => {
    setSubmitting(false);
    setDirection("");
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
        {title}
      </h3>

      {arc && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-1 text-xs font-medium text-gray-500">当前弧线大纲</div>
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{arc}</ReactMarkdown>
          </div>
        </div>
      )}

      {remaining.length > 0 && (
        <div className="rounded border border-gray-200 bg-gray-50 p-3 text-sm">
          <div className="mb-1 text-xs font-medium text-gray-500">剩余章节标题</div>
          <ul className="list-inside list-decimal space-y-0.5 text-gray-700">
            {remaining.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      <textarea
        value={direction}
        onChange={(e) => setDirection(e.target.value)}
        disabled={isDisabled}
        placeholder="输入调整方向（直接回车/留空 → 使用默认 / 取消）"
        rows={4}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      />
      <div className="flex gap-2">
        <button
          onClick={() => handleSubmit("")}
          disabled={isDisabled}
          className="rounded bg-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳" : "用默认 / 取消"}
        </button>
        <button
          onClick={() => handleSubmit(direction.trim())}
          disabled={isDisabled || !direction.trim()}
          className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {submitting ? "⏳ 提交中..." : "提交调整方向"}
        </button>
      </div>
    </div>
  );
}
