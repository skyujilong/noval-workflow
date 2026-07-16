// 章末实体发现·入库筛选表单：展示本章新建卡 + 已有卡动态更新，用户勾选真正入库的项。
// 默认全选（保留全部），取消一次性碎屑/过场项后提交。
// resume 值：选中 key 的 JSON 字符串数组，如 ["new:圣焰皇家骑士团","update:陆默"]；空数组表示本章不入库任何项。

import { useEffect, useMemo, useState } from "react";
import type { EntitySelectConfirmPayload } from "../../lib/interruptTypes";

interface Props {
  payload: EntitySelectConfirmPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function EntitySelectConfirmForm({ payload, onSubmit, disabled }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  // 所有候选 key（新建卡 + 更新），用于全选/计数
  const allKeys = useMemo(
    () => [
      ...payload.new_cards.map((c) => c.key),
      ...payload.updates.map((u) => u.key),
    ],
    [payload],
  );

  // 默认全选：保留全部
  useEffect(() => {
    setSelected(new Set(allKeys));
  }, [allKeys]);

  useEffect(() => {
    if (!disabled) setSubmitting(false);
  }, [disabled]);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const allChecked = selected.size === allKeys.length && allKeys.length > 0;
  const handleSelectAll = () => {
    setSelected(allChecked ? new Set() : new Set(allKeys));
  };

  const handleConfirm = () => {
    setSubmitting(true);
    onSubmit(JSON.stringify(Array.from(selected)));
  };

  const isDisabled = disabled || submitting;
  const droppedCount = allKeys.length - selected.size;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">实体入库筛选</h3>
        {allKeys.length > 0 && (
          <button
            type="button"
            onClick={handleSelectAll}
            disabled={isDisabled}
            className="text-xs text-blue-600 hover:text-blue-800 disabled:text-gray-400"
          >
            {allChecked ? "取消全选" : "全选"}
          </button>
        )}
      </div>

      <p className="text-sm text-gray-500">
        默认全选。取消一次性碎屑（遣散费、情绪道具、一幕 NPC 等）后提交，未选中的不会写入卡库。
      </p>

      {/* 新建卡 */}
      {payload.new_cards.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-4">
          <h4 className="mb-3 font-medium text-gray-700">
            🆕 新建卡（{payload.new_cards.length}）
          </h4>
          <div className="space-y-2">
            {payload.new_cards.map((c) => (
              <label
                key={c.key}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 transition-colors hover:bg-gray-100"
              >
                <input
                  type="checkbox"
                  checked={selected.has(c.key)}
                  onChange={() => toggle(c.key)}
                  disabled={isDisabled}
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1 text-sm">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-semibold text-gray-800">{c.name}</span>
                    <span className="rounded border bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {c.type}
                    </span>
                  </div>
                  {c.summary && <div className="text-gray-500">{c.summary}</div>}
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* 动态更新 */}
      {payload.updates.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-4">
          <h4 className="mb-3 font-medium text-gray-700">
            🔄 已有卡更新（{payload.updates.length}）
          </h4>
          <div className="space-y-2">
            {payload.updates.map((u) => (
              <label
                key={u.key}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 transition-colors hover:bg-gray-100"
              >
                <input
                  type="checkbox"
                  checked={selected.has(u.key)}
                  onChange={() => toggle(u.key)}
                  disabled={isDisabled}
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1 text-sm">
                  <div className="mb-1 font-semibold text-gray-800">{u.name}</div>
                  <div className="space-y-0.5 text-gray-500">
                    {Object.entries(u.changes).map(([field, value]) => (
                      <div key={field}>
                        <span className="text-blue-500">{field}：</span>
                        {value}
                      </div>
                    ))}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* 空态兜底（正常不会走到——空草稿在后端已直接跳过 interrupt） */}
      {allKeys.length === 0 && (
        <div className="rounded border border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
          本章无新实体、无动态更新。
        </div>
      )}

      {/* 操作区 */}
      <div className="flex items-center justify-between pt-2">
        <span className="text-sm text-gray-500">
          {droppedCount > 0 ? `将剔除 ${droppedCount} 项` : "全部保留"}
        </span>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={isDisabled}
          className="rounded bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 transition-colors"
        >
          {submitting ? "⏳ 处理中..." : `确认入库（${selected.size} 项）`}
        </button>
      </div>
    </div>
  );
}
