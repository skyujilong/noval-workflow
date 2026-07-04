// 可勾选 + 可就地编辑的整改卡片：提案卡与精炼候选卡共用。
// 自己管理「放大编辑」弹窗开合，其余状态由父组件持有（受控 text/selected）。

import { useState } from "react";
import { FieldExpandDialog } from "../state/FieldExpandDialog";

interface Props {
  title: string;
  /** 冲突/标签等次要标记 */
  badge?: string;
  /** 是否用告警色渲染 badge（如「覆盖原规则」） */
  badgeWarn?: boolean;
  /** 小注释（如 rationale） */
  hint?: string;
  text: string;
  selected: boolean;
  disabled?: boolean;
  onToggle: () => void;
  onChange: (text: string) => void;
}

export function EditableDirectiveCard({
  title,
  badge,
  badgeWarn,
  hint,
  text,
  selected,
  disabled,
  onToggle,
  onChange,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={
        "rounded border p-3 " + (selected ? "border-blue-300 bg-blue-50/40" : "border-gray-200")
      }
    >
      <div className="mb-1.5 flex items-center gap-2">
        <input
          type="checkbox"
          checked={selected}
          disabled={disabled}
          onChange={onToggle}
          className="h-4 w-4"
        />
        <span className="text-sm font-medium text-gray-700">{title}</span>
        {badge && (
          <span
            className={
              "rounded px-1.5 py-0.5 text-[10px] " +
              (badgeWarn ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-500")
            }
          >
            {badge}
          </span>
        )}
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="ml-auto text-xs text-gray-400 hover:text-blue-600"
        >
          ⤢ 放大
        </button>
      </div>
      <textarea
        value={text}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className="w-full rounded border border-gray-200 p-2 font-mono text-xs"
      />
      {hint && <p className="mt-1 text-[11px] text-gray-400">{hint}</p>}

      <FieldExpandDialog
        open={expanded}
        title={title}
        value={text}
        disabled={disabled}
        onChange={onChange}
        onClose={() => setExpanded(false)}
      />
    </div>
  );
}
