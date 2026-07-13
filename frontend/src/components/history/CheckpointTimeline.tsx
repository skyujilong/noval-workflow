// 历史回溯面板：列出 thread 的 checkpoint，点击查看快照，支持从此点重跑。

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getThreadHistory } from "../../lib/langgraph";
import { EMPTY_NOVEL_STATE, type NovelState } from "../../lib/types";

interface Props {
  threadId: string | null;
  onReplay: (checkpointId: string) => void;
}

interface CpItem {
  checkpointId: string;
  createdAt: string;
  next: string[];
  state: NovelState;
}

// 审稿步骤(review_X)重跑时，回退到其上游 prepare_X 检查点再重跑。
// 原因：prepare_* 才是读取「按小说提示词覆盖」的唯一入口（registry.get_prompt_pack），
// 它把解析后的 task_prompt/system_context 烤进 checkpoint 状态，审稿子图只消费这两个
// 烤好的字段。若直接从 review_X 重跑会复用旧烤死值，改了提示词配置也不生效；
// 回退到 prepare_X 重跑 → prepare 重新读盘 → 新提示词即时生效。
function resolveReplayTarget(
  sel: CpItem,
  items: CpItem[]
): { checkpointId: string; viaPrepare?: string } {
  const reviewNode = sel.next.find((n) => n.startsWith("review_"));
  if (!reviewNode) return { checkpointId: sel.checkpointId };
  const prepareNode = "prepare_" + reviewNode.slice("review_".length);
  // items 按时间倒序（index 0 最新）；prepare_X 早于 review_X → 索引更大，向后找最近的一个。
  const selIdx = items.findIndex((it) => it.checkpointId === sel.checkpointId);
  for (let i = selIdx + 1; i < items.length; i++) {
    if (items[i].next.includes(prepareNode)) {
      return { checkpointId: items[i].checkpointId, viaPrepare: prepareNode };
    }
  }
  return { checkpointId: sel.checkpointId }; // 兜底：历史被截断找不到 prepare 时按原点重跑
}

export function CheckpointTimeline({ threadId, onReplay }: Props) {
  const [items, setItems] = useState<CpItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CpItem | null>(null);

  // 拉取（或重新拉取）当前 thread 的 checkpoint 历史。
  // useEffect（threadId 变化时）与「刷新」按钮共用这一份逻辑。
  const load = useCallback(() => {
    if (!threadId) return;
    setLoading(true);
    setError(null);
    getThreadHistory(threadId, 30)
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

  useEffect(() => {
    // 🔒 历史状态隔离：只要 threadId 变化（不管是不是 null），先清空旧状态
    // 防止从小说 A 切换到小说 B 时，短暂显示小说 A 的历史快照
    setItems([]);
    setSelected(null);
    load();
  }, [threadId, load]);

  // 选中点的实际重跑目标：审稿步骤自动回退到上游 prepare_X，其余按原点。
  const replayTarget = useMemo(
    () => (selected ? resolveReplayTarget(selected, items) : null),
    [selected, items]
  );

  if (!threadId) return null;

  return (
    // 用 flex-1 + min-h-0 而非 h-full：父级 <aside> 里已有 tab bar 占位，
    // h-full 会让本组件取到 aside 整高，多占 tab bar 那段 → 底部被外层
    // overflow-hidden 裁掉，表现为最后一条 item 只显示一半。
    // min-h-0 是 flex column 里子级 overflow-y-auto 生效的必要条件
    // （默认 min-height:auto 会让 flex item 撑到内容全高、绕过滚动）。
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b p-3">
        <h3 className="text-sm font-semibold text-gray-700">历史回溯</h3>
        <button
          onClick={load}
          disabled={loading}
          title="刷新"
          className="flex items-center justify-center rounded px-2 py-1 text-gray-500 transition-colors hover:bg-gray-100 disabled:opacity-50"
        >
          <RefreshCw size={16} strokeWidth={2} className={loading ? "animate-spin" : undefined} />
        </button>
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
              onClick={() => replayTarget && onReplay(replayTarget.checkpointId)}
              className="rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700"
            >
              从此点重跑
            </button>
          </div>
          {replayTarget?.viaPrepare && (
            <div className="mb-1 rounded bg-amber-50 px-2 py-1 text-[11px] leading-snug text-amber-700">
              审稿步骤：重跑将从上游 <b>{replayTarget.viaPrepare}</b> 开始，以重新读取该小说的提示词配置。
            </div>
          )}
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
