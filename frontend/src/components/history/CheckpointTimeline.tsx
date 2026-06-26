// 历史回溯面板：列出 thread 的 checkpoint，点击查看快照，支持从此点分叉。

import { useEffect, useState } from "react";
import { forkThread, getThreadHistory } from "../../lib/langgraph";
import { EMPTY_NOVEL_STATE, type NovelState } from "../../lib/types";

interface Props {
  threadId: string | null;
  onForked: (newThreadId: string) => void;
}

interface CpItem {
  checkpointId: string;
  createdAt: string;
  next: string[];
  state: NovelState;
}

export function CheckpointTimeline({ threadId, onForked }: Props) {
  const [items, setItems] = useState<CpItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CpItem | null>(null);

  useEffect(() => {
    if (!threadId) {
      setItems([]);
      setSelected(null);
      return;
    }
    setLoading(true);
    setError(null);
    getThreadHistory(threadId, 100)
      .then((hist) => {
        const list: CpItem[] = hist.map((h) => ({
          checkpointId:
            (h.checkpoint as { checkpoint_id?: string })?.checkpoint_id ?? "",
          createdAt:
            (h.metadata as { created_at?: string })?.created_at ?? "",
          next: (h as { next?: string[] }).next ?? [],
          state: { ...EMPTY_NOVEL_STATE, ...((h.values ?? {}) as Partial<NovelState>) },
        }));
        setItems(list);
        setSelected(null);
      })
      .catch((e) => setError(`加载历史失败：${(e as Error).message}`))
      .finally(() => setLoading(false));
  }, [threadId]);

  const fork = async (cp: CpItem) => {
    try {
      const t = await forkThread(threadId!, cp.checkpointId);
      onForked(t.thread_id);
    } catch (e) {
      setError(`分叉失败：${(e as Error).message}`);
    }
  };

  if (!threadId) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <h3 className="text-sm font-semibold text-gray-700">历史回溯</h3>
      </div>
      {error && (
        <div className="m-2 rounded bg-red-50 p-2 text-xs text-red-600">{error}</div>
      )}
      {loading && <div className="p-3 text-xs text-gray-400">加载中…</div>}
      <div className="flex-1 overflow-y-auto">
        {items.map((cp, i) => (
          <div
            key={cp.checkpointId || i}
            className="border-b p-2 hover:bg-gray-50"
          >
            <button
              onClick={() => setSelected(cp)}
              className="block w-full text-left"
            >
              <div className="text-xs font-medium text-gray-700">
                #{items.length - i} {cp.next.join(",") || "（结束）"}
              </div>
              <div className="text-xs text-gray-400">
                {cp.createdAt || `节点 ${i}`}
              </div>
              <div className="truncate text-xs text-gray-500">
                {cp.state.novel_name || "—"} · 已写 {cp.state.total_chapters_written ?? 0} 章
              </div>
            </button>
          </div>
        ))}
      </div>

      {selected && (
        <div className="border-t bg-gray-50 p-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium text-gray-600">快照预览</span>
            <button
              onClick={() => fork(selected)}
              className="rounded bg-amber-600 px-2 py-0.5 text-xs text-white hover:bg-amber-700"
            >
              从此点分叉
            </button>
          </div>
          <div className="max-h-40 overflow-y-auto rounded bg-white p-2 text-xs text-gray-700">
            <div>
              <b>小说：</b>
              {selected.state.novel_name || "—"}
            </div>
            <div>
              <b>当前节点：</b>
              {selected.next.join(", ") || "—"}
            </div>
            <div>
              <b>章节进度：</b>
              {selected.state.total_chapters_written ?? 0} 章
            </div>
            <div>
              <b>当前草稿类型：</b>
              {selected.state.review_type || "—"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
