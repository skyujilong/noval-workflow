// 次要角色「提升为重要角色」面板（Part 2）。
//
// 声明式渲染 usePromoteCharacter 的会话状态机：选目标 role → 生成 LLM 草稿 → 逐字段审改 → 落库。
// 全部异步/状态逻辑在 hook 里，本组件只映射 session → UI。

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PROMOTABLE_ROLES, type CharacterPromotePatch } from "../../lib/langgraph";
import type { UsePromoteCharacter } from "../../hooks/usePromoteCharacter";
import type { EntityCard } from "../../lib/types";

// 4 个可审改的深层字段（role 固定为目标值，不在此列）。label 供表单展示。
const DEEP_FIELDS: Array<{ key: keyof CharacterPromotePatch; label: string; hint: string }> = [
  { key: "appearance", label: "外貌", hint: "体貌基线：身形/气质/年龄段/大致长相 + 可选识别特征" },
  { key: "hidden_persona", label: "隐藏人设", hint: "暗线秘密/异常/隐藏能力/立场偏差，可后期反转" },
  { key: "arc_trajectory", label: "全书弧光", hint: "开篇→收官心性/立场/认知迭代大势（只写大势）" },
  { key: "ability_contract", label: "底牌契约", hint: "初始锚点+全书成长天花板+隐藏杀手锏（非战斗角色可留空）" },
];

// 现状卡里供审改参照的只读字段（提升不改这些）。
function CurrentRef({ card }: { card: EntityCard }) {
  const rows: Array<[string, string | undefined]> = [
    ["定位", card.summary],
    ["性格", card.personality],
    ["能力", card.abilities],
    ["动机", card.motivation],
    ["关系", card.relations],
  ];
  return (
    <div className="rounded border border-gray-200 bg-gray-50/70 p-2 text-[11px] text-gray-600">
      <div className="mb-1 font-medium text-gray-500">现状卡（提升不改这些，仅作参照）</div>
      {rows
        .filter(([, v]) => v)
        .map(([k, v]) => (
          <div key={k}>
            <span className="text-gray-400">{k} · </span>
            {v}
          </div>
        ))}
    </div>
  );
}

export function PromoteCharacterPanel({ ctl }: { ctl: UsePromoteCharacter }) {
  const { session, busy, close, setTargetRole, generateDraft, setField, apply } = ctl;
  if (!session) return null;
  const { card, targetRole, phase, draft, error } = session;
  const hasDraft = phase === "editing" || phase === "applying";

  return (
    <Dialog open onOpenChange={(o) => !o && close()}>
      <DialogContent className="flex max-h-[86vh] w-[92vw] max-w-[720px] flex-col gap-3">
        <DialogHeader>
          <DialogTitle>提升为重要角色 · {card.name}</DialogTitle>
          <DialogDescription>
            为原「次要角色」补齐深层设计（隐藏人设/全书弧光/底牌契约）。LLM 生成草稿后可逐字段审改，落库即覆盖。
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-700">
            {error}
          </div>
        ) : null}

        <CurrentRef card={card} />

        {/* 目标 role 选择 */}
        <div>
          <div className="mb-1 text-xs font-medium text-gray-600">目标定位</div>
          <div className="flex flex-wrap gap-1.5">
            {PROMOTABLE_ROLES.map((r) => (
              <button
                key={r}
                type="button"
                disabled={busy}
                onClick={() => setTargetRole(r)}
                className={`rounded border px-2 py-1 text-[11px] transition-colors disabled:opacity-50 ${
                  targetRole === r
                    ? "border-indigo-400 bg-indigo-50 font-medium text-indigo-700"
                    : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {/* 草稿区：未出草稿时给「生成草稿」按钮；出草稿后给逐字段审改 */}
        {hasDraft && draft ? (
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
            {DEEP_FIELDS.map((f) => (
              <div key={f.key}>
                <div className="mb-0.5 flex items-baseline justify-between">
                  <span className="text-xs font-medium text-gray-600">{f.label}</span>
                  <span className="text-[10px] text-gray-400">{f.hint}</span>
                </div>
                <Textarea
                  value={draft[f.key]}
                  disabled={busy}
                  onChange={(e) => setField(f.key, e.target.value)}
                  className="min-h-[64px] resize-y text-sm leading-relaxed"
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded border border-dashed border-gray-200 py-4 text-center text-[11px] text-gray-400">
            {phase === "drafting" ? "正在生成深层设计草稿…（LLM 需十几秒）" : "选好目标定位后，点「生成草稿」由 LLM 补齐深层设计"}
          </div>
        )}

        {/* 底部操作 */}
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" onClick={close} disabled={busy}>
            取消
          </Button>
          {hasDraft ? (
            <>
              <Button variant="outline" onClick={generateDraft} disabled={busy}>
                重新生成
              </Button>
              <Button onClick={apply} disabled={busy}>
                {phase === "applying" ? "落库中…" : "确认落库"}
              </Button>
            </>
          ) : (
            <Button onClick={generateDraft} disabled={busy}>
              {phase === "drafting" ? "生成中…" : "生成草稿"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
