// 脑爆产物整合 review 抽屉：一次性展示 + 编辑 4 个正式设定字段（取代原 4 个逐项 confirm）。
//
// resume 值为 dict（透传 langgraph Command(resume=...)）：
//   - 保存并推进 → { action: "advance", core_theme, world_building, [power_system], core_conflicts }
//     后端 brainstorm_extract_review 覆写 state 后路由到 collect_user_inputs
//   - 返回脑爆继续修改 → { action: "back_to_chat" }
//     后端复位 brainstorm_done、不写字段、路由回 brainstorm_chat
//
// has_power_system 由脑爆聊天页底部 switch 决定并已在结束脑爆前写回 state——本抽屉不再让用户
// 覆盖 flag，只按 payload.has_power_system 展示/隐藏力量体系编辑区。若用户结束脑爆后发现开关
// 选错，走「返回脑爆继续修改」回到聊天页调整 switch 即可。

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import {
  buildBrainstormReviewAdvanceResume,
  buildBrainstormReviewBackResume,
  type BrainstormExtractReviewPayload,
  type BrainstormReviewResume,
} from "../../lib/interruptTypes";

interface Props {
  payload: BrainstormExtractReviewPayload;
  onSubmit: (value: BrainstormReviewResume) => void;
  disabled?: boolean;
}

export function BrainstormExtractReview({ payload, onSubmit, disabled }: Props) {
  const [coreTheme, setCoreTheme] = useState(payload.core_theme ?? "");
  const [worldBuilding, setWorldBuilding] = useState(payload.world_building ?? "");
  const [powerSystem, setPowerSystem] = useState(payload.power_system ?? "");
  const [coreConflicts, setCoreConflicts] = useState(payload.core_conflicts ?? "");
  const [submitting, setSubmitting] = useState(false);

  // payload 更新（replay / 新 interrupt）或提交结束时重置本地 state
  useEffect(() => {
    setSubmitting(false);
    setCoreTheme(payload.core_theme ?? "");
    setWorldBuilding(payload.world_building ?? "");
    setPowerSystem(payload.power_system ?? "");
    setCoreConflicts(payload.core_conflicts ?? "");
  }, [payload, disabled]);

  // 三个必填字段（力量体系视 has_power_system 可选，不算必填）
  const canAdvance =
    coreTheme.trim().length > 0 &&
    worldBuilding.trim().length > 0 &&
    coreConflicts.trim().length > 0;

  const isDisabled = disabled || submitting;

  const handleAdvance = () => {
    if (!canAdvance) return;
    setSubmitting(true);
    onSubmit(
      buildBrainstormReviewAdvanceResume({
        core_theme: coreTheme,
        world_building: worldBuilding,
        power_system: payload.has_power_system ? powerSystem : undefined,
        core_conflicts: coreConflicts,
      })
    );
  };

  const handleBackToChat = () => {
    setSubmitting(true);
    onSubmit(buildBrainstormReviewBackResume());
  };

  // Sheet 挂载即打开；组件卸载（resume 后 interrupt 消失）自动关闭。
  // 遮罩 / Esc 关闭视为「返回脑爆继续修改」不太直观 —— 阻止关闭，强制走底部按钮。
  return (
    <Sheet open={true}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>脑爆产物 · 整合 Review</SheetTitle>
          <SheetDescription>{payload.message}</SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-4">
          <FieldBlock
            label="核心主题与立意"
            value={coreTheme}
            onChange={setCoreTheme}
            disabled={isDisabled}
            required
          />
          <FieldBlock
            label="世界观设定"
            value={worldBuilding}
            onChange={setWorldBuilding}
            disabled={isDisabled}
            required
          />
          {payload.has_power_system && (
            <FieldBlock
              label="力量体系"
              value={powerSystem}
              onChange={setPowerSystem}
              disabled={isDisabled}
              // 力量体系视聊天页开关可选，不做必填校验
            />
          )}
          <FieldBlock
            label="核心冲突"
            value={coreConflicts}
            onChange={setCoreConflicts}
            disabled={isDisabled}
            required
          />
        </div>

        <SheetFooter className="items-center gap-2 border-t px-6 py-4 sm:gap-2">
          <div className="mr-auto text-xs text-gray-400">
            {canAdvance ? "" : "至少填写主题、世界观、核心冲突后可推进"}
          </div>
          <Button variant="ghost" onClick={handleBackToChat} disabled={isDisabled}>
            返回脑爆继续修改
          </Button>
          <Button onClick={handleAdvance} disabled={isDisabled || !canAdvance}>
            {submitting ? "⏳ 提交中…" : "保存并推进"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

interface FieldBlockProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  required?: boolean;
}

function FieldBlock({ label, value, onChange, disabled, required }: FieldBlockProps) {
  const showEmpty = required && !value.trim();
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-gray-800">{label}</label>
        {required && <span className="text-xs text-red-500">*</span>}
        {showEmpty && (
          <span className="text-xs text-amber-600">（必填）</span>
        )}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={8}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm leading-relaxed focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
      />
    </div>
  );
}
