// Interrupt 分发器：按 payload.type 权威字段查表分发到对应表单（见 interruptTypes.ts
// 的 TYPE_TO_FORM 契约表）。表单提交时调用 onSubmit(resumeValue)，由上层 useRun.resume() 恢复 run。

import { useRef } from "react";
import { formKindOfPayload } from "../../lib/interruptTypes";
import { ArcConfirmForm } from "./ArcConfirmForm";
import { BrainstormConfirmForm } from "./BrainstormConfirmForm";
import { BrainstormGateForm } from "./BrainstormGateForm";
import { ArcTitlesConfirmForm } from "./ArcTitlesConfirmForm";
import { AskContinueForm } from "./AskContinueForm";
import { DirectionForm } from "./DirectionForm";
import { EntryGateForm } from "./EntryGateForm";
import { ForeshadowingReviewForm } from "./ForeshadowingReviewForm";
import { ForeshadowPruneConfirmForm } from "./ForeshadowPruneConfirmForm";
import { HumanReviewForm } from "./HumanReviewForm";
import { UserInputsForm } from "./UserInputsForm";

interface Props {
  payload: unknown;
  onSubmit: (value: unknown) => void;
  disabled?: boolean;
}

export function InterruptHandler({ payload, onSubmit, disabled }: Props) {
  const kind = formKindOfPayload(payload);
  // fallback 场景的 textarea 引用，避免脆弱的 DOM 遍历
  const fallbackTextareaRef = useRef<HTMLTextAreaElement>(null);

  // 用 payload.type 作为 key 强制重挂载：同类型不同 interrupt 也会创建新组件实例，
  // 彻底解决组件复用导致的 submitting=true 永久锁死问题（root cause fix）。
  const formKey = String((payload as { type?: unknown })?.type ?? "unknown");

  switch (kind) {
    // brainstorm_chat 不在此处渲染——由 NovelWorkspace 接管为连续聊天视图。
    case "brainstorm_gate":
      return (
        <BrainstormGateForm
          key={formKey}
          payload={payload as Parameters<typeof BrainstormGateForm>[0]["payload"]}
          onSubmit={(v) => onSubmit(v)}
          disabled={disabled}
        />
      );

    case "brainstorm_confirm":
      return (
        <BrainstormConfirmForm
          key={formKey}
          payload={payload as Parameters<typeof BrainstormConfirmForm>[0]["payload"]}
          onSubmit={(v) => onSubmit(v)}
          disabled={disabled}
        />
      );

    case "user_inputs":
      return (
        <UserInputsForm
          key={formKey}
          payload={payload as Parameters<typeof UserInputsForm>[0]["payload"]}
          onSubmit={(v) => onSubmit(v)}
          disabled={disabled}
        />
      );

    case "human_review":
      return (
        <HumanReviewForm
          key={formKey}
          payload={payload as Parameters<typeof HumanReviewForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "ask_continue":
      return (
        <AskContinueForm
          key={formKey}
          payload={payload as Parameters<typeof AskContinueForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "entry_gate":
      return (
        <EntryGateForm
          key={formKey}
          payload={payload as Parameters<typeof EntryGateForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "direction":
    case "arc_direction":
      return (
        <DirectionForm
          key={formKey}
          payload={payload as Parameters<typeof DirectionForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "arc_confirm":
      return (
        <ArcConfirmForm
          key={formKey}
          payload={payload as Parameters<typeof ArcConfirmForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "arc_titles_confirm":
      return (
        <ArcTitlesConfirmForm
          key={formKey}
          payload={payload as Parameters<typeof ArcTitlesConfirmForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "foreshadowing_review":
      return (
        <ForeshadowingReviewForm
          key={formKey}
          payload={payload as Parameters<typeof ForeshadowingReviewForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    case "foreshadow_prune_confirm":
      return (
        <ForeshadowPruneConfirmForm
          key={formKey}
          payload={payload as Parameters<typeof ForeshadowPruneConfirmForm>[0]["payload"]}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      );

    default:
      return (
        <div key={formKey} className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-800">未识别的中断</h3>
          <p className="text-xs text-amber-600">
            payload 缺少 type 字段或 type 未在 TYPE_TO_FORM 登记（后端契约故障，显式暴露）。
          </p>
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
