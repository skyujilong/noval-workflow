// 登场实体卡(entity_cards) 的结构化 JSON 源码编辑器——「编辑当前状态」抽屉里的可编辑入口。
//
// entity_cards 是 list[EntityCard]，字段多 + type 条件字段，故用「JSON 源码编辑 + 实时校验 +
// 解析成功即结构化预览」而非逐字段表单：手写 JSON 直观、可批量改，预览让用户确认落地形态。
// 校验逻辑在 lib/editableState.ts::parseEntityCardsJson，与后端 EntityCard 对齐；非法时父层
// (useStateEditor.entityCardsError) 禁止保存。
//
// 手改安全性：卡库覆盖语义、章前 _merge_cards 对已有卡 canon 锁定只 append、章末 _apply_updates
// 只改 status/owner/motivation——手改核心字段不会被后续章节冲掉（不同于 chapter_plan 的滚动覆盖）。

import { Textarea } from "@/components/ui/textarea";
import { parseEntityCardsJson } from "../../lib/editableState";
import { EntityCardsReadonly } from "./EntityCardsReadonly";

interface Props {
  /** JSON 源码草稿（受控） */
  value: string;
  /** 校验错误（null = 合法）——来自 useStateEditor.entityCardsError */
  error: string | null;
  /** run 进行中 / 后台忙：只读展示，不可编辑 */
  disabled: boolean;
  onChange: (value: string) => void;
}

export function EntityCardsEditor({ value, error, disabled, onChange }: Props) {
  // 解析成功时用结构化面板预览「保存后长什么样」；失败时预览区让位给错误提示。
  const parsed = parseEntityCardsJson(value);

  return (
    <div className="space-y-2">
      <Textarea
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={12}
        spellCheck={false}
        className="font-mono text-xs"
        placeholder='[{"name": "张三", "type": "人物", "aliases": ["三哥"], "summary": "…", "appearance": "…"}]'
      />
      {error ? (
        <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-600">
          ⚠ {error}
        </div>
      ) : (
        <div className="rounded border border-gray-100 bg-white p-2">
          <div className="mb-1 text-[10px] text-gray-400">保存后预览（结构化）</div>
          <EntityCardsReadonly cards={parsed.value ?? []} />
        </div>
      )}
    </div>
  );
}
