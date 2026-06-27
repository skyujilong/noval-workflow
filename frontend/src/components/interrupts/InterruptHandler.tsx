// Interrupt 分发器：根据 payload 结构判别中断类型，渲染对应表单。
// 表单提交时调用 onSubmit(resumeValue)，由上层 useRun.resume() 恢复 run。

import { useRef } from "react";
import { detectInterruptKind } from "../../lib/interruptTypes";
import type { SubgraphState } from "../../lib/langgraph";
import { ArcConfirmForm } from "./ArcConfirmForm";
import { ArcTitlesConfirmForm } from "./ArcTitlesConfirmForm";
import { AskContinueForm } from "./AskContinueForm";
import { DirectionForm } from "./DirectionForm";
import { EntryGateForm } from "./EntryGateForm";
import { HumanReviewForm } from "./HumanReviewForm";
import { UserInputsForm } from "./UserInputsForm";

interface Props {
  payload: unknown;
  subgraphState: SubgraphState | null;
  onSubmit: (value: unknown) => void;
  disabled?: boolean;
}

export function InterruptHandler({ payload, subgraphState, onSubmit, disabled }: Props) {
  const kind = detectInterruptKind(payload);
  // fallback 场景的 textarea 引用，避免脆弱的 DOM 遍历
  const fallbackTextareaRef = useRef<HTMLTextAreaElement>(null);

  switch (kind) {
    case "user_inputs":
      return (
        <UserInputsForm
          payload={payload as Parameters<typeof UserInputsForm>[0]["payload"]}
          onSubmit={(v) => onSubmit(v)}
          disabled={disabled}
        />
      );

    case "human_review":
      return (
        <HumanReviewForm
          payload={payload as Parameters<typeof HumanReviewForm>[0]["payload"]}
          subgraphState={subgraphState}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "ask_continue":
      return (
        <AskContinueForm
          payload={payload as Parameters<typeof AskContinueForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "entry_gate":
      return (
        <EntryGateForm
          payload={payload as Parameters<typeof EntryGateForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "direction":
    case "arc_direction":
      return (
        <DirectionForm
          payload={payload as Parameters<typeof DirectionForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
          title={kind === "arc_direction" ? "弧线大纲调整方向" : "调整方向"}
        />
      );

    case "arc_confirm":
      return (
        <ArcConfirmForm
          payload={payload as Parameters<typeof ArcConfirmForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "arc_titles_confirm":
      return (
        <ArcTitlesConfirmForm
          payload={payload as Parameters<typeof ArcTitlesConfirmForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    default:
      return (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-800">未识别的中断</h3>
          <pre className="overflow-x-auto rounded bg-gray-100 p-3 text-xs text-gray-700">
            {JSON.stringify(payload, null, 2)}
          </pre>
          <textarea
            ref={fallbackTextareaRef}
            placeholder="输入任意文本作为 resume 值提交…"
            rows={3}
            disabled={disabled}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                onSubmit(fallbackTextareaRef.current?.value ?? "");
              }
            }}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-100"
          />
          <button
            onClick={() => onSubmit(fallbackTextareaRef.current?.value ?? "")}
            disabled={disabled}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
          >
            提交
          </button>
          <p className="text-xs text-gray-400">Cmd/Ctrl+Enter 提交</p>
        </div>
      );
  }
}
