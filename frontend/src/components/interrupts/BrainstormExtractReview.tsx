// 脑爆产物整合 review 面板：一次性展示 + 编辑 4 个正式设定字段（取代原 4 个逐项 confirm）。
//
// 渲染形态：静态右侧面板，与其他 interrupt 表单一致（不再用抽屉——interrupt 消费后
// 父层 InterruptHandler 会直接卸载本组件，抽屉的开关动画/受控 open 逻辑纯属画蛇添足，
// 反而带来「关闭动画期间又被打开一次」这类时序 bug）。
//
// resume 值为 dict（透传 langgraph Command(resume=...)）：
//   - 保存并推进 → { action: "advance", core_theme, world_building, [power_system], core_conflicts }
//     后端 brainstorm_extract_review 覆写 state 后路由到 collect_user_inputs
//   - 返回脑爆继续修改 → { action: "back_to_chat" }
//     后端复位 brainstorm_done、不写字段、路由回 brainstorm_chat
//
// has_power_system 由脑爆聊天页底部 switch 决定并已在结束脑爆前写回 state——本面板不再让用户
// 覆盖 flag，只按 payload.has_power_system 展示/隐藏力量体系编辑区。若用户结束脑爆后发现开关
// 选错，走「返回脑爆继续修改」回到聊天页调整 switch 即可。

import { useState } from "react";
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
  // 4 个字段的初始值来自 payload；父层 InterruptHandler 用 payload.type 作 key，
  // 每个新 interrupt 都会重挂载本组件，useState 的初值即本次生命周期唯一值。
  const [coreTheme, setCoreTheme] = useState(payload.core_theme ?? "");
  const [worldBuilding, setWorldBuilding] = useState(payload.world_building ?? "");
  const [powerSystem, setPowerSystem] = useState(payload.power_system ?? "");
  const [coreConflicts, setCoreConflicts] = useState(payload.core_conflicts ?? "");
  const [submitting, setSubmitting] = useState(false);

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

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-gray-800">脑爆产物 · 整合 Review</h3>
        <p className="mt-1 text-sm text-gray-500">{payload.message}</p>
      </div>

      {/* AI 收尾总结：与 chat 气泡里 AI 最后一段流式内容一致的原文（同一 LLM 调用产出），
          让 review 与 chat 视觉关联。旧 thread 缺 finalize_summary 时整块不渲染，向后兼容。
          默认展开以立即可读；用户折叠后腾出空间给下方 4 字段编辑区。 */}
      {payload.finalize_summary && (
        <details
          open
          className="rounded-md border border-blue-200 bg-blue-50/50 p-3 text-sm"
        >
          <summary className="cursor-pointer select-none font-medium text-blue-800">
            AI 收尾总结
          </summary>
          <div className="mt-2 whitespace-pre-wrap leading-relaxed text-gray-700">
            {payload.finalize_summary}
          </div>
        </details>
      )}

      <div className="space-y-5">
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

      <div className="flex flex-col items-stretch gap-2 border-t pt-4 sm:flex-row sm:items-center">
        <div className="mr-auto text-xs text-gray-400">
          {canAdvance ? "" : "至少填写主题、世界观、核心冲突后可推进"}
        </div>
        <Button variant="ghost" onClick={handleBackToChat} disabled={isDisabled}>
          返回脑爆继续修改
        </Button>
        <Button onClick={handleAdvance} disabled={isDisabled || !canAdvance}>
          {submitting ? "⏳ 提交中…" : "保存并推进"}
        </Button>
      </div>
    </div>
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
