// 脑爆产物整合 review 面板：一次性展示 + 编辑 4 个正式设定字段（取代原 4 个逐项 confirm）。
//
// 渲染形态：静态右侧面板，与其他 interrupt 表单一致（不再用抽屉——interrupt 消费后
// 父层 InterruptHandler 会直接卸载本组件，抽屉的开关动画/受控 open 逻辑纯属画蛇添足，
// 反而带来「关闭动画期间又被打开一次」这类时序 bug）。
//
// 每个字段用「预览 / 编辑」双 tab：
//   - 预览：react-markdown + remark-gfm，力量体系里 LLM 输出的 GFM 表格能真渲染成表格
//     （靠 @tailwindcss/typography 的 .prose 提供表格边框样式）。
//   - 编辑：保留 textarea，用户改完切回预览即可可视化确认。
// 首次进入面板时：字段有值 → 预览；字段为空且必填 → 落到编辑态帮用户第一眼就能填。
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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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

  // v2 保真度改造：finalize_confirm 节点纯 python 切分完整版 markdown 后，切不到内容的字段名
  // 累在 payload.missing_fields 里。前端把这份 Set 化便于各 FieldBlock O(1) 判断，
  // 命中的字段头部渲染黄色警告条提示用户手填或返回聊天补充。
  const missing = new Set(payload.missing_fields ?? []);

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

      <div className="space-y-5">
        <FieldBlock
          label="核心主题与立意"
          value={coreTheme}
          onChange={setCoreTheme}
          disabled={isDisabled}
          required
          missing={missing.has("core_theme")}
        />
        <FieldBlock
          label="世界观设定"
          value={worldBuilding}
          onChange={setWorldBuilding}
          disabled={isDisabled}
          required
          missing={missing.has("world_building")}
        />
        {payload.has_power_system && (
          <FieldBlock
            label="力量体系"
            value={powerSystem}
            onChange={setPowerSystem}
            disabled={isDisabled}
            missing={missing.has("power_system")}
            // 力量体系视聊天页开关可选，不做必填校验
          />
        )}
        <FieldBlock
          label="核心冲突"
          value={coreConflicts}
          onChange={setCoreConflicts}
          disabled={isDisabled}
          required
          missing={missing.has("core_conflicts")}
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
  /** v2 保真度改造：完整版 markdown 里没切到本节 → 头部渲染黄色警告条提示用户手填或返回聊天。 */
  missing?: boolean;
}

// 单字段的预览/编辑双 tab 容器：初值有内容 → 预览态可视化确认；空且必填 → 编辑态便于立即补录。
// 预览用 react-markdown + remark-gfm 渲染，力量体系 LLM 输出的 GFM 表格能真表格显示。
function FieldBlock({ label, value, onChange, disabled, required, missing }: FieldBlockProps) {
  // 初始 mode 派生：字段有内容且非仅空白 → 预览；否则编辑。用户切换后靠自己 useState 记忆。
  // missing=true 时（切分失败）也强制落到编辑态，方便用户第一眼就能补录。
  const [mode, setMode] = useState<"preview" | "edit">(() =>
    value.trim().length > 0 && !missing ? "preview" : "edit"
  );
  const showEmpty = required && !value.trim();

  return (
    <div className="space-y-1.5">
      {missing && (
        <div className="rounded border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
          ⚠️ AI 整理的完整版里没找到这一节，请手填或返回聊天补充
        </div>
      )}
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-gray-800">{label}</label>
        {required && <span className="text-xs text-red-500">*</span>}
        {showEmpty && <span className="text-xs text-amber-600">（必填）</span>}
        <div className="ml-auto inline-flex overflow-hidden rounded border border-gray-300 text-xs">
          <button
            type="button"
            onClick={() => setMode("preview")}
            className={`px-2 py-0.5 transition ${
              mode === "preview"
                ? "bg-blue-500 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            预览
          </button>
          <button
            type="button"
            onClick={() => setMode("edit")}
            className={`border-l border-gray-300 px-2 py-0.5 transition ${
              mode === "edit"
                ? "bg-blue-500 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
          >
            编辑
          </button>
        </div>
      </div>
      {mode === "preview" ? (
        // prose 类由 @tailwindcss/typography 提供表格边框/间距样式；max-h + overflow-y-auto 防超长
        <div className="prose prose-sm max-w-none max-h-96 overflow-y-auto rounded border border-gray-200 bg-white p-3">
          {value.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
          ) : (
            <div className="text-sm italic text-gray-400">（暂无内容，切到「编辑」填写）</div>
          )}
        </div>
      ) : (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          rows={12}
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm leading-relaxed focus:border-blue-500 focus:outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
        />
      )}
    </div>
  );
}
