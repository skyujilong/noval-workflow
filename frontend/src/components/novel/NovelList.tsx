// 左侧小说列表：列出所有 thread，支持新建与选择。

import type { ThreadInfo } from "../../lib/langgraph";

interface Props {
  threads: ThreadInfo[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  onRefresh: () => void;
}

export function NovelList({
  threads,
  loading,
  error,
  selectedId,
  onSelect,
  onCreate,
  onRefresh,
}: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-3 border-b">
        <h2 className="text-sm font-semibold text-gray-700">小说项目</h2>
        <div className="flex gap-1">
          <button
            onClick={onRefresh}
            title="刷新"
            className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
          >
            ⟳
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
          const name =
            t.metadata?.novel_name ||
            (t.values?.novel_name as string | undefined) ||
            `未命名 ${t.thread_id.slice(0, 6)}`;
          const chapters = t.values?.total_chapters_written ?? 0;
          const isActive = t.thread_id === selectedId;
          return (
            <button
              key={t.thread_id}
              onClick={() => onSelect(t.thread_id)}
              className={
                "block w-full border-b px-3 py-2 text-left hover:bg-gray-50 " +
                (isActive ? "bg-blue-50 border-l-4 border-l-blue-600" : "")
              }
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
          );
        })}
      </div>
    </div>
  );
}
