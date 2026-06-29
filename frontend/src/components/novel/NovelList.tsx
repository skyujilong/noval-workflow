// 左侧小说列表：列出所有 thread，支持新建、选择与删除。

import { useState } from "react";
import { AlertTriangle, RefreshCw, Settings2, Trash2 } from "lucide-react";
import type { ThreadInfo } from "../../lib/langgraph";

interface Props {
  threads: ThreadInfo[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  onRefresh: () => void;
  onConfig: (thread: ThreadInfo) => void;
  onDelete: (threadId: string) => Promise<boolean>;
}

export function NovelList({
  threads,
  loading,
  error,
  selectedId,
  onSelect,
  onCreate,
  onRefresh,
  onConfig,
  onDelete,
}: Props) {
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const handleDeleteClick = (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    setDeleteConfirmId(threadId);
  };

  const handleConfirmDelete = async () => {
    if (!deleteConfirmId) return;
    setDeletingId(deleteConfirmId);
    const success = await onDelete(deleteConfirmId);
    if (success) {
      setDeleteConfirmId(null);
    }
    setDeletingId(null);
  };

  const handleCancelDelete = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setDeleteConfirmId(null);
  };

  const getThreadName = (t: ThreadInfo) => {
    const realName =
      t.metadata?.novel_name ||
      (t.values?.novel_name as string | undefined) ||
      "";
    return realName || `未命名 ${t.thread_id.slice(0, 6)}`;
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-3 border-b">
        <h2 className="text-sm font-semibold text-gray-700">小说项目</h2>
        <div className="flex gap-1">
          <button
            onClick={onRefresh}
            title="刷新"
            className="rounded px-2 py-1 text-gray-500 hover:bg-gray-100 transition-colors flex items-center justify-center"
          >
            <RefreshCw size={16} strokeWidth={2} />
          </button>
          <button
            onClick={onCreate}
            className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
          >
            + 新建
          </button>
        </div>
      </div>

      {error && (
        <div className="m-2 rounded bg-red-50 p-2 text-xs text-red-600">{error}</div>
      )}

      <div className="flex-1 overflow-y-auto">
        {loading && threads.length === 0 && (
          <div className="p-3 text-xs text-gray-400">加载中…</div>
        )}
        {!loading && threads.length === 0 && (
          <div className="p-3 text-xs text-gray-400">
            暂无小说，点击「新建」开始创作。
          </div>
        )}
        {threads.map((t) => {
          const name = getThreadName(t);
          const hasName = !!(
            t.metadata?.novel_name || t.values?.novel_name);
          const chapters = t.values?.total_chapters_written ?? 0;
          const isActive = t.thread_id === selectedId;
          return (
            <div
              key={t.thread_id}
              className={
                "flex items-stretch border-b hover:bg-gray-50 " +
                (isActive ? "bg-blue-50 border-l-4 border-l-blue-600" : "")
              }
            >
              <button
                onClick={() => onSelect(t.thread_id)}
                className="min-w-0 flex-1 px-3 py-2 text-left"
              >
                <div className="truncate text-sm font-medium text-gray-800">
                  {name}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-gray-400">
                  <span>{chapters > 0 ? `已写 ${chapters} 章` : "未开始"}</span>
                  <span>·</span>
                  <span>{t.status}</span>
                </div>
              </button>
              <button
                type="button"
                disabled={!hasName}
                title={hasName ? "提示词配置" : "请先完成基础信息后再配置"}
                onClick={(e) => {
                  e.stopPropagation();
                  onConfig(t);
                }}
                className="shrink-0 px-2.5 text-gray-400 hover:text-blue-600 disabled:cursor-not-allowed disabled:text-gray-200 disabled:hover:text-gray-200 transition-colors flex items-center justify-center"
              >
                <Settings2 size={16} strokeWidth={2} />
              </button>
              <button
                type="button"
                title="删除小说"
                onClick={(e) => handleDeleteClick(e, t.thread_id)}
                className="shrink-0 px-2.5 text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors flex items-center justify-center"
              >
                <Trash2 size={16} strokeWidth={2} />
              </button>
            </div>
          );
        })}
      </div>

      {/* 删除确认对话框 */}
      {deleteConfirmId && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-white rounded-xl p-6 max-w-sm mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-800">
                确认删除
              </h3>
            </div>
            <div className="ml-[52px]">
              <p className="text-sm text-gray-600 mb-2">
                确定要删除小说
                <span className="font-medium text-gray-800">
                  「{getThreadName(threads.find(t => t.thread_id === deleteConfirmId)!)}」
                </span>
                吗？
              </p>
              <p className="text-xs text-red-500 mb-6 flex items-start gap-1.5">
                <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                此操作不可撤销，删除后所有章节和数据将永久丢失。
              </p>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={handleCancelDelete}
                disabled={!!deletingId}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={!!deletingId}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors flex items-center gap-2"
              >
                {deletingId ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    删除中…
                  </>
                ) : (
                  <>
                    <Trash2 size={16} />
                    确认删除
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
