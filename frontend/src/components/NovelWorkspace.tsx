// 单本小说运行时容器：由 App 以 key={threadId} 渲染，切换小说时整树重挂载，
// 故每本小说一个独立 useRun 实例，跨小说隔离由 React 协调天然保证（无需手写守卫）。
// 渲染中部节点图 + 右侧「中断表单 / 流式 / 小说详情」，并自管运行相关的副作用：
//   - autoStart：因「新建」挂载时自动启动 run
//   - 回填：collect_user_inputs 完成后把 novel_name 写回 thread metadata
//   - 状态上报：把 currentNode/running/error 上报给 App 渲染 header / 错误条
//   - replay：经 ref 暴露给 App 左侧「历史」面板

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useState,
} from "react";
import { GraphView } from "./graph/GraphView";
import { InterruptHandler } from "./interrupts/InterruptHandler";
import { BrainstormChat } from "./interrupts/BrainstormChat";
import { ChapterReader } from "./novel/ChapterReader";
import { NovelDetail } from "./novel/NovelDetail";
import { useRun } from "../hooks/useRun";
import { updateThreadMeta } from "../lib/langgraph";
import type { GraphEdge, GraphNode, ThreadMeta } from "../lib/langgraph";
import { BRAINSTORM_END, InterruptType } from "../lib/interruptTypes";

export interface NovelWorkspaceHandle {
  replay: (checkpointId: string) => void;
}

export interface RunStatus {
  /** 该状态属于哪个 thread——供 App 校验归属，丢弃切换瞬间的陈旧上报 */
  threadId: string;
  currentNode: string;
  running: boolean;
  error: string | null;
}

interface Props {
  threadId: string;
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  /** 本组件因「新建」而挂载时为 true：自动启动 run，停在 collect_user_inputs */
  autoStart: boolean;
  /** 当前 thread 的 metadata（用于把 novel_name 回填进去） */
  threadMeta?: ThreadMeta;
  /** 回填后刷新左侧小说列表 */
  onRefreshThreads: () => void;
  /** 把运行状态上报给 App 渲染 header / 错误条 */
  onStatusChange: (status: RunStatus) => void;
}

export const NovelWorkspace = forwardRef<NovelWorkspaceHandle, Props>(
  function NovelWorkspace(
    {
      threadId,
      graphNodes,
      graphEdges,
      autoStart,
      threadMeta,
      onRefreshThreads,
      onStatusChange,
    },
    ref
  ) {
    const {
      state,
      currentNode,
      interrupt,
      running,
      loading,
      error,
      start,
      resume,
      replay,
      refresh,
      streamingContent,
      streamingNode,
    } = useRun(threadId);
    const [rightTab, setRightTab] = useState<"detail" | "reader">("detail");

    // 脑爆聊天连续视图：等输入（brainstorm_chat interrupt）或 AI 流式回复（brainstorm_respond）
    // 两态都命中，使 BrainstormChat 跨态持续挂载，输入/滚动态不丢。confirm 步与 gate 走普通表单。
    const interruptType =
      interrupt && typeof interrupt.payload === "object" && interrupt.payload
        ? (interrupt.payload as { type?: string }).type
        : undefined;
    // 仅聊天循环（chat/respond/extract）命中连续视图；gate 与 confirm 走普通表单，故排除。
    const inBrainstorm =
      interruptType === InterruptType.BRAINSTORM_CHAT ||
      (running &&
        (currentNode === "brainstorm_chat" ||
          currentNode === "brainstorm_respond" ||
          currentNode === "brainstorm_extract" ||
          streamingNode === "brainstorm_respond"));

    // 脑爆 AI 回复的流式打字机门控：只要在脑爆运行中、有流式增量内容，就显示。
    // 不强绑 streamingNode === "brainstorm_respond" 精确匹配——回复期间 streamingNode 常被
    // 上一拍 brainstorm_chat 的 updates 事件占着，精确匹配会一直 false，导致 token 在
    // streamingContent 里累积却从不渲染（最终只在 refresh 后以历史气泡整段出现）。
    // 改为「有增量即流」，并用 streamingNode 显式排除 extract（其产出是 JSON，不该进聊天气泡）。
    const brainstormStreaming =
      running &&
      streamingContent.length > 0 &&
      streamingNode !== "brainstorm_extract";

    // 暴露 replay 给 App（左侧「历史」面板「从此点重跑」）
    useImperativeHandle(ref, () => ({ replay }), [replay]);

    // 运行状态上报（带 threadId 供 App 校验归属）；header / 错误条由 App 渲染，
    // App 内按 threadId 丢弃非当前小说的上报，并做值比较去抖。
    useEffect(() => {
      onStatusChange({ threadId, currentNode, running, error });
    }, [threadId, currentNode, running, error, onStatusChange]);

    // 自动启动：新建小说挂载后立刻启动，停在 collect_user_inputs
    useEffect(() => {
      if (autoStart && !interrupt && !running && !state.novel_name) {
        void start();
      }
    }, [autoStart, interrupt, running, state.novel_name, start]);

    // collect_user_inputs 完成后，把 novel_name 回填到 thread metadata
    useEffect(() => {
      if (!state.novel_name || threadMeta?.novel_name) return;
      void updateThreadMeta(threadId, { ...threadMeta, novel_name: state.novel_name });
      onRefreshThreads();
    }, [threadId, state.novel_name, threadMeta, onRefreshThreads]);

    return (
      <>
        {/* 中部：节点图 */}
        <main className="flex-1 bg-gray-50">
          <GraphView
            schemaNodes={graphNodes}
            schemaEdges={graphEdges}
            currentNode={currentNode}
          />
        </main>

        {/* 右侧：中断表单 / 流式 / 小说详情（顺序刻意保留：resume 期保留旧中断表单） */}
        <aside className="relative flex-1 overflow-y-auto border-l bg-white">
          {inBrainstorm ? (
            <BrainstormChat
              summary={state.brainstorm_summary ?? ""}
              history={state.brainstorm_history ?? []}
              streaming={brainstormStreaming}
              streamingContent={streamingContent}
              awaitingInput={interruptType === InterruptType.BRAINSTORM_CHAT}
              onSend={(m) => void resume(m)}
              onEnd={() => void resume(BRAINSTORM_END)}
              disabled={running}
            />
          ) : interrupt ? (
            <div className="p-4">
              <InterruptHandler
                payload={interrupt.payload}
                onSubmit={(value) => void resume(value)}
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
          ) : loading ? (
            // 首次快照拉取中：显示加载占位，避免在真实 state 回来前闪现空态详情 + 「开始创作」
            <div className="flex h-full items-center justify-center p-4 text-sm text-gray-400">
              加载中…
            </div>
          ) : error && !state.novel_name ? (
            // 加载失败且尚无内容可展示：显示错误页 + 重试，而非误导性的空态「开始创作」。
            // 有内容时（已跑过的小说）不走这里，避免一次刷新失败就顶掉正在看的成稿，错误交顶部错误条提示。
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
              <div className="text-sm font-medium text-red-600">加载失败</div>
              <div className="max-w-xs break-words text-xs text-gray-500">{error}</div>
              <button
                onClick={() => void refresh()}
                className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
              >
                重试
              </button>
            </div>
          ) : (
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
                      onClick={() => void refresh()}
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
          )}
        </aside>
      </>
    );
  }
);
