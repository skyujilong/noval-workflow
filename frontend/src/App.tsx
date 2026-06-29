// 顶层布局：左侧小说列表/历史，中部节点图，右侧中断表单或小说详情。

import { useCallback, useEffect, useState } from "react";
import { GraphView } from "./components/graph/GraphView";
import { CheckpointTimeline } from "./components/history/CheckpointTimeline";
import { InterruptHandler } from "./components/interrupts/InterruptHandler";
import { ChapterReader } from "./components/novel/ChapterReader";
import { NovelDetail } from "./components/novel/NovelDetail";
import { NovelList } from "./components/novel/NovelList";
import { PromptOverrideModal } from "./components/novel/PromptOverrideModal";
import { useGraphSchema } from "./hooks/useGraphSchema";
import { useRun } from "./hooks/useRun";
import { useThreads } from "./hooks/useThreads";
import { updateThreadMeta } from "./lib/langgraph";
import type { ThreadInfo } from "./lib/langgraph";

type LeftTab = "novels" | "history";

export default function App() {
  const { threads, loading, error, refresh, create } = useThreads();
  const [selectedId, setSelectedId] = useState<string | null>(
    () => localStorage.getItem("selectedThreadId")
  );
  const [autoStart, setAutoStart] = useState(false);
  const [leftTab, setLeftTab] = useState<LeftTab>("novels");
  const [rightTab, setRightTab] = useState<"detail" | "reader">("detail");
  const [configThread, setConfigThread] = useState<ThreadInfo | null>(null);

  const { state, currentNode, interrupt, running, error: runError, start, resume, replay, refresh: refreshRun, streamingContent, streamingNode } =
    useRun(selectedId);

  const { nodes: graphNodes, edges: graphEdges } = useGraphSchema(true);

  // 新建小说：创建 thread → 选中 → 自动启动 run
  const handleCreate = useCallback(async () => {
    const t = await create();
    if (t) {
      setSelectedId(t.thread_id);
      setAutoStart(true);
    }
  }, [create]);

  // 持久化 selectedId，页面刷新后恢复
  useEffect(() => {
    if (selectedId) localStorage.setItem("selectedThreadId", selectedId);
    else localStorage.removeItem("selectedThreadId");
  }, [selectedId]);

  // 自动启动：新创建的空 thread 立刻启动，停在 collect_user_inputs
  useEffect(() => {
    if (autoStart && selectedId && !interrupt && !running && !state.novel_name) {
      setAutoStart(false);
      void start();
    }
  }, [autoStart, selectedId, interrupt, running, state.novel_name, start]);

  // collect_user_inputs 完成后，把 novel_name 回填到 thread metadata
  useEffect(() => {
    if (!selectedId || !state.novel_name) return;
    const t = threads.find((x) => x.thread_id === selectedId);
    if (t && !t.metadata?.novel_name) {
      void updateThreadMeta(selectedId, { ...t.metadata, novel_name: state.novel_name });
      void refresh();
    }
  }, [selectedId, state.novel_name, threads, refresh]);

  const handleSubmit = useCallback(
    (value: unknown) => {
      void resume(value);
    },
    [resume]
  );

  const handleReplay = useCallback((checkpointId: string) => {
    void replay(checkpointId);
  }, [replay]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b bg-white px-4 py-2">
        <h1 className="text-base font-semibold text-gray-800">小说创作工作台</h1>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>当前节点：{currentNode || "—"}</span>
          {running && (
            <span className="flex items-center gap-1 text-blue-500">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              运行中
            </span>
          )}
        </div>
      </header>

      {runError && (
        <div className="bg-red-50 px-4 py-1 text-xs text-red-600">{runError}</div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧：小说列表 / 历史 */}
        <aside className="flex w-64 flex-col border-r bg-white">
          <div className="flex border-b text-xs">
            <button
              onClick={() => setLeftTab("novels")}
              className={
                "flex-1 py-2 " +
                (leftTab === "novels"
                  ? "border-b-2 border-blue-600 font-medium text-blue-600"
                  : "text-gray-500")
              }
            >
              小说
            </button>
            <button
              onClick={() => setLeftTab("history")}
              className={
                "flex-1 py-2 " +
                (leftTab === "history"
                  ? "border-b-2 border-blue-600 font-medium text-blue-600"
                  : "text-gray-500")
              }
            >
              历史
            </button>
          </div>
          {leftTab === "novels" ? (
            <NovelList
              threads={threads}
              loading={loading}
              error={error}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setRightTab("detail");
              }}
              onCreate={handleCreate}
              onRefresh={refresh}
              onConfig={setConfigThread}
            />
          ) : (
            <CheckpointTimeline threadId={selectedId} onReplay={handleReplay} />
          )}
        </aside>

        {/* 中部：节点图 */}
        <main className="flex-1 bg-gray-50">
          <GraphView
            schemaNodes={graphNodes}
            schemaEdges={graphEdges}
            currentNode={currentNode}
          />
        </main>

        {/* 右侧：中断表单 / 小说详情（与中部节点图各占剩余宽度一半） */}
        <aside className="relative flex-1 overflow-y-auto border-l bg-white">
          {interrupt ? (
            <div className="p-4">
              <InterruptHandler
                payload={interrupt.payload}
                onSubmit={handleSubmit}
                disabled={running}
              />
            </div>
          ) : running ? (
            <div className="h-full overflow-y-auto p-4">
              {/* 头部：节点名 + 状态指示 */}
              <div className="mb-3 flex items-center gap-2">
                <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                <span className="text-sm font-medium text-gray-700">
                  正在生成：{streamingNode || currentNode || "初始化中…"}
                </span>
              </div>
              {/* 流式内容展示区 - 纯文本 + 换行，简单高效 */}
              {streamingContent ? (
                <div className="rounded-lg bg-gray-50 p-4 text-sm text-gray-700 whitespace-pre-wrap font-mono">
                  {streamingContent}
                </div>
              ) : (
                <div className="flex items-center justify-center py-12 text-sm text-gray-400">
                  正在初始化生成…
                </div>
              )}
            </div>
          ) : selectedId ? (
            <>
              <div className="flex border-b text-xs">
                <button
                  onClick={() => setRightTab("detail")}
                  className={
                    "flex-1 py-2 " +
                    (rightTab === "detail"
                      ? "border-b-2 border-blue-600 font-medium text-blue-600"
                      : "text-gray-500")
                  }
                >
                  小说详情
                </button>
                <button
                  onClick={() => setRightTab("reader")}
                  disabled={!state.novel_name}
                  className={
                    "flex-1 py-2 disabled:text-gray-300 " +
                    (rightTab === "reader"
                      ? "border-b-2 border-blue-600 font-medium text-blue-600"
                      : "text-gray-500")
                  }
                >
                  阅读章节
                </button>
              </div>
              {rightTab === "detail" ? (
                <>
                  <NovelDetail state={state} />
                  {!state.novel_name && (
                    <div className="px-4 pb-4">
                      <button
                        onClick={() => void start()}
                        disabled={running}
                        className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
                      >
                        开始创作
                      </button>
                    </div>
                  )}
                  <div className="px-4 pb-4">
                    <button
                      onClick={() => void refreshRun()}
                      className="w-full rounded border border-gray-300 px-4 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                    >
                      刷新状态
                    </button>
                  </div>
                </>
              ) : (
                <ChapterReader state={state} />
              )}
            </>
          ) : (
            <div className="flex h-full items-center justify-center p-4 text-center text-sm text-gray-400">
              从左侧选择一个小说，或点击「新建」开始创作。
            </div>
          )}
        </aside>
      </div>

      <PromptOverrideModal
        open={!!configThread}
        novelName={
          configThread?.metadata?.novel_name ||
          (configThread?.values?.novel_name as string | undefined) ||
          ""
        }
        genre={(configThread?.values?.genre as string | undefined) || "通用"}
        onClose={() => setConfigThread(null)}
      />
    </div>
  );
}
