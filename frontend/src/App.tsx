// 顶层外壳：左侧小说列表/历史 + 整体布局 + header。每本小说的运行时（节点图 + 右侧
// 中断/流式/详情）下放到 <NovelWorkspace key={selectedId}>，切换小说即整树重挂载，
// 跨小说隔离由 React 协调天然保证；App 自身不再持有 useRun。

import { useCallback, useEffect, useRef, useState } from "react";
import { GraphView } from "./components/graph/GraphView";
import { CheckpointTimeline } from "./components/history/CheckpointTimeline";
import { NovelList } from "./components/novel/NovelList";
import { PromptOverrideModal } from "./components/novel/PromptOverrideModal";
import {
  NovelWorkspace,
  type NovelWorkspaceHandle,
  type RunStatus,
} from "./components/NovelWorkspace";
import { useGraphSchema } from "./hooks/useGraphSchema";
import { useThreads } from "./hooks/useThreads";
import type { ThreadInfo } from "./lib/langgraph";

type LeftTab = "novels" | "history";

const EMPTY_STATUS: RunStatus = { threadId: "", currentNode: "", running: false, error: null };

export default function App() {
  const { threads, loading, error, refresh, create, delete: deleteThread } = useThreads();
  const [selectedId, setSelectedId] = useState<string | null>(
    () => localStorage.getItem("selectedThreadId")
  );
  const [autoStart, setAutoStart] = useState(false);
  // 自动模式总开关（跨小说全局偏好，localStorage 持久化）：打开后章节循环的人工中断自动应答
  const [lazyMode, setLazyMode] = useState<boolean>(
    () => localStorage.getItem("lazyModeOn") === "1"
  );
  // 「长线规划自动化」子开关（全局偏好）：默认关=遇长线章节规划点停回人工，防剧情偏移
  const [autoLongPlan, setAutoLongPlan] = useState<boolean>(
    () => localStorage.getItem("lazyLongPlanOn") === "1"
  );
  // 当从列表点「▶」进入 pending 卡住的 thread 时置为 true，workspace 挂载后自动触发一次 continueRun。
  // 与 autoStart 语义并行：autoStart 面向「新建自动 start」；autoContinue 面向「pending 一键继续」。
  const [autoContinue, setAutoContinue] = useState(false);
  const [leftTab, setLeftTab] = useState<LeftTab>("novels");
  const [configThread, setConfigThread] = useState<ThreadInfo | null>(null);
  // 当前小说的运行状态（由 NovelWorkspace 上报），供 header / 错误条渲染
  const [status, setStatus] = useState<RunStatus>(EMPTY_STATUS);
  const workspaceRef = useRef<NovelWorkspaceHandle>(null);
  // 最新选中的 threadId（render 期赋值），供状态上报回调按归属过滤
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const {
    nodes: graphNodes,
    edges: graphEdges,
    error: graphError,
    refetch: refetchGraph,
  } = useGraphSchema(true);

  // 当前选中小说在 /novels/summary 轮询里的那条（含权威 status：idle/busy/interrupted/error）。
  const selectedThread = selectedId
    ? threads.find((t) => t.thread_id === selectedId)
    : undefined;

  // 状态上报：按 threadId 丢弃非当前选中小说的上报（切换瞬间的陈旧上报），
  // 再做值比较去抖（值未变则复用旧引用，避免无谓重渲染）。
  const handleStatusChange = useCallback((s: RunStatus) => {
    if (s.threadId !== selectedIdRef.current) return;
    setStatus((prev) =>
      prev.currentNode === s.currentNode &&
      prev.running === s.running &&
      prev.error === s.error
        ? prev
        : s
    );
  }, []);

  // 选中已有小说：切换并复位运行状态（新 workspace 挂载后会重新上报）
  // 若小说是 busy 状态，乐观设为 running，避免切换后短暂显示详情再跳运行中
  const handleSelect = useCallback(
    (id: string) => {
      const t = threads.find((x) => x.thread_id === id);
      if (t?.status === "busy") {
        setStatus({
          threadId: id,
          currentNode: "",
          running: true,
          error: null,
        });
      } else {
        setStatus(EMPTY_STATUS);
      }
      setSelectedId(id);
      setAutoStart(false);
      setAutoContinue(false);
    },
    [threads]
  );

  // 列表卡片「▶」：选中该 thread；若已选中则直接触发 continueRun，
  // 否则设置 autoContinue，workspace 挂载后由本组件自动触发一次（见下 useEffect）。
  const handleContinue = useCallback(
    (id: string) => {
      if (id === selectedId) {
        workspaceRef.current?.continueRun();
        return;
      }
      setStatus(EMPTY_STATUS);
      setSelectedId(id);
      setAutoStart(false);
      setAutoContinue(true);
    },
    [selectedId]
  );

  // 新建小说：创建 thread → 选中 → 自动启动 run
  const handleCreate = useCallback(async () => {
    const t = await create();
    if (t) {
      setSelectedId(t.thread_id);
      setAutoStart(true);
      setAutoContinue(false);
      setStatus(EMPTY_STATUS);
    }
  }, [create]);

  const handleReplay = useCallback((checkpointId: string) => {
    workspaceRef.current?.replay(checkpointId);
  }, []);

  // autoContinue 消费回调：稳定引用，避免每次 App render 新建导致 workspace 里 effect deps 抖动。
  const handleAutoContinueConsumed = useCallback(() => setAutoContinue(false), []);

  // 持久化 selectedId，页面刷新后恢复
  useEffect(() => {
    if (selectedId) localStorage.setItem("selectedThreadId", selectedId);
    else localStorage.removeItem("selectedThreadId");
  }, [selectedId]);

  // 持久化自动模式开关
  useEffect(() => {
    localStorage.setItem("lazyModeOn", lazyMode ? "1" : "0");
  }, [lazyMode]);

  // 持久化长线规划自动化子开关
  useEffect(() => {
    localStorage.setItem("lazyLongPlanOn", autoLongPlan ? "1" : "0");
  }, [autoLongPlan]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b bg-white px-4 py-2">
        <h1 className="text-base font-semibold text-gray-800">小说创作工作台</h1>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>当前节点：{status.currentNode || "—"}</span>
          {status.running && (
            <span className="flex items-center gap-1 text-blue-500">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              运行中
            </span>
          )}
        </div>
      </header>

      {status.error && (
        <div className="bg-red-50 px-4 py-1 text-xs text-red-600">{status.error}</div>
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
              onSelect={handleSelect}
              onCreate={handleCreate}
              onRefresh={refresh}
              onConfig={setConfigThread}
              onContinue={handleContinue}
              onDelete={async (id) => {
                const success = await deleteThread(id);
                if (success && id === selectedId) {
                  setSelectedId(null);
                  setStatus(EMPTY_STATUS);
                }
                return success;
              }}
            />
          ) : (
            <CheckpointTimeline threadId={selectedId} onReplay={handleReplay} />
          )}
        </aside>

        {/* 中部 + 右侧：单本小说运行时；key 切换即整树重挂载 */}
        {selectedId ? (
          <NovelWorkspace
            key={selectedId}
            ref={workspaceRef}
            threadId={selectedId}
            graphNodes={graphNodes}
            graphEdges={graphEdges}
            graphError={graphError}
            onRetryGraph={refetchGraph}
            autoStart={autoStart}
            autoContinue={autoContinue}
            onAutoContinueConsumed={handleAutoContinueConsumed}
            threadMeta={selectedThread?.metadata}
            summaryBusy={selectedThread?.status === "busy"}
            onRefreshThreads={refresh}
            onStatusChange={handleStatusChange}
            lazyMode={lazyMode}
            onLazyModeChange={setLazyMode}
            autoLongPlan={autoLongPlan}
            onAutoLongPlanChange={setAutoLongPlan}
          />
        ) : (
          <>
            <main className="flex-1 bg-gray-50">
              <GraphView
                schemaNodes={graphNodes}
                schemaEdges={graphEdges}
                currentNode=""
                schemaError={graphError}
                onRetrySchema={refetchGraph}
              />
            </main>
            <aside className="relative flex-1 overflow-y-auto border-l bg-white">
              <div className="flex h-full items-center justify-center p-4 text-center text-sm text-gray-400">
                从左侧选择一个小说，或点击「新建」开始创作。
              </div>
            </aside>
          </>
        )}
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
