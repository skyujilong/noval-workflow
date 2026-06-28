// 伏笔精简确认表单：展示 LLM 建议删除的伏笔，用户勾选确认。
// resume 值：JSON 字符串格式的待删ID数组，如 ["F01", "F02"]，空数组表示不删除。

import { useEffect, useState } from "react";
import type { ForeshadowPruneConfirmPayload } from "../../lib/interruptTypes";

interface Props {
  payload: ForeshadowPruneConfirmPayload;
  onSubmit: (value: string) => void;
  disabled?: boolean;
}

export function ForeshadowPruneConfirmForm({ payload, onSubmit, disabled }: Props) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  // 默认全选所有建议删除的
  useEffect(() => {
    if (payload.to_delete && payload.to_delete.length > 0) {
      setSelectedIds(new Set(payload.to_delete.map((d) => d.id)));
    }
  }, [payload]);

  useEffect(() => {
    if (!disabled) {
      setSubmitting(false);
    }
  }, [disabled]);

  const handleToggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedIds.size === payload.to_delete.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(payload.to_delete.map((d) => d.id)));
    }
  };

  const handleConfirm = () => {
    setSubmitting(true);
    // 返回选中的ID数组JSON字符串
    onSubmit(JSON.stringify(Array.from(selectedIds)));
  };

  const handleSkip = () => {
    setSubmitting(true);
    // 空数组表示不删除任何内容
    onSubmit("[]");
  };

  const isDisabled = disabled || submitting;
  const afterPendingCount = payload.pending_count - selectedIds.size;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-gray-800">伏笔台账精简建议</h3>
      </div>

      {/* 分析概览 */}
      <div className="rounded border border-blue-200 bg-blue-50 p-4">
        <h4 className="mb-2 font-medium text-blue-800">📊 分析概览</h4>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="text-gray-700">
            <span className="font-semibold text-rose-600">S 级核心伏笔</span>：{payload.s_level_count} 个（全部保留）
          </div>
          <div className="text-gray-700">
            <span className="font-semibold text-amber-600">A 级次要伏笔</span>：{payload.a_level_count} 个
          </div>
          <div className="text-gray-700">
            <span className="font-semibold text-gray-600">当前悬置伏笔</span>：{payload.pending_count} 个
          </div>
          <div className="text-gray-700">
            <span className="font-semibold text-gray-600">当前已收伏笔</span>：{payload.collected_count} 个
          </div>
        </div>
      </div>

      {/* 建议删除列表 */}
      {payload.to_delete.length > 0 ? (
        <div className="rounded border border-gray-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="font-medium text-gray-700">
              🗑️ 建议删除（{payload.to_delete.length} 个）
            </h4>
            <button
              type="button"
              onClick={handleSelectAll}
              disabled={isDisabled}
              className="text-xs text-blue-600 hover:text-blue-800 disabled:text-gray-400"
            >
              {selectedIds.size === payload.to_delete.length ? "取消全选" : "全选"}
            </button>
          </div>

          <div className="space-y-2">
            {payload.to_delete.map((entry) => (
              <label
                key={entry.id}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 transition-colors hover:bg-gray-100"
              >
                <input
                  type="checkbox"
                  checked={selectedIds.has(entry.id)}
                  onChange={() => handleToggle(entry.id)}
                  disabled={isDisabled}
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div className="flex-1 text-sm">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-semibold text-gray-800">{entry.id}</span>
                    <span className="text-gray-700">{entry.name}</span>
                    {entry.planted_batch && (
                      <span className="rounded border bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                        批次: {entry.planted_batch}
                      </span>
                    )}
                    {entry.freedom && (
                      <span className="rounded border bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                        自由度: {entry.freedom}
                      </span>
                    )}
                  </div>
                  <div className="text-gray-500">
                    <span className="text-rose-500">原因：</span>
                    {entry.reason}
                  </div>
                </div>
              </label>
            ))}
          </div>

          {/* 精简后预览 */}
          <div className="mt-3 rounded border-t border-gray-200 pt-3 text-sm text-gray-500">
            ✨ 精简后预计剩余 <span className="font-semibold text-green-600">{Math.max(0, afterPendingCount)}</span> 个悬置伏笔
          </div>
        </div>
      ) : (
        <div className="rounded border border-green-200 bg-green-50 p-6 text-center">
          <div className="text-2xl">🎉</div>
          <div className="mt-2 font-medium text-green-700">当前伏笔结构合理，无需精简</div>
        </div>
      )}

      {/* 整体建议 */}
      {payload.suggestion && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="text-sm text-amber-800">💡 {payload.suggestion}</div>
        </div>
      )}

      {/* 操作区 */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={handleSkip}
          disabled={isDisabled}
          className="flex-1 rounded border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "⏳ 处理中..." : "跳过，不删除"}
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={isDisabled || selectedIds.size === 0}
          className="flex-1 rounded bg-rose-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-rose-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "⏳ 处理中..." : `确认精简（删除 ${selectedIds.size} 个）`}
        </button>
      </div>
    </div>
  );
}
