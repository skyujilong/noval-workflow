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
import { StateEditPanel } from "./state/StateEditPanel";
import { PromptEvolutionModal } from "./novel/PromptEvolutionModal";
import { useRun } from "../hooks/useRun";
import { updateThreadMeta, updateThreadState } from "../lib/langgraph";
import type { GraphEdge, GraphNode, ThreadMeta } from "../lib/langgraph";
import { BRAINSTORM_END, InterruptType } from "../lib/interruptTypes";
import type { NovelState } from "../lib/types";
import { EVOLVABLE_REVIEW_TYPES } from "../lib/types";

/** 尽力取「最近一次人工打回意见」预填进化抽屉：优先持久的 human_feedback，
 *  否则从 review_history 里取最后一条人工发言（剥掉 generate 追加的「输出规范」尾巴）；
 *  首条人工发言是任务提示词而非打回意见，故仅在有 >1 条人工发言时才回退取用。 */
function latestHumanFeedback(state: NovelState): string {
  if (state.human_feedback?.trim()) return state.human_feedback.trim();
  const humans = (state.review_history ?? []).filter((h) => h.role === "human");
  if (humans.length <= 1) return "";
  return humans[humans.length - 1].content.split("【输出规范】")[0].trim();
}


export interface NovelWorkspaceHandle {
  replay: (checkpointId: string) => void;
  /** 显式触发「继续执行」——列表卡片的 ▶ 按钮用它，无需进入详情面板 */
  continueRun: () => void;
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
  /** 图结构拉取错误（自动重试全失败后）—— 透传给中部 GraphView 显示错误态 */
  graphError?: string | null;
  /** 图结构手动重试入口 —— 透传给 GraphView 的"重试"按钮 */
  onRetryGraph?: () => void;
  /** 本组件因「新建」而挂载时为 true：自动启动 run，停在 collect_user_inputs */
  autoStart: boolean;
  /** 因列表「▶」进入 pending thread 时为 true：等首次快照拉回后自动触发一次 continueRun。
   *  与 autoStart 语义并行；两者互斥（App 层保证）。触发后由 onAutoContinueConsumed 回调复位。 */
  autoContinue?: boolean;
  /** autoContinue 消费回调：workspace 触发后通知 App 把标记清掉，避免 refresh 抖动重复触发。 */
  onAutoContinueConsumed?: () => void;
  /** 当前 thread 的 metadata（用于把 novel_name 回填进去） */
  threadMeta?: ThreadMeta;
  /** 该 thread 在 /novels/summary 轮询里的 status 是否为 busy（后端正有 run 在执行）。
   *  权威的「同 thread_id 正忙」信号——本地 running 之外再加这道闸，挡掉陈旧 UI / 后台 run
   *  导致的对同一 thread 的重复 resume（否则同一 thread_id 触发两次不同的东西 → 混乱）。 */
  summaryBusy?: boolean;
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
      graphError,
      onRetryGraph,
      autoStart,
      autoContinue,
      onAutoContinueConsumed,
      threadMeta,
      summaryBusy,
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
      pendingResume,
      start,
      resume,
      continueRun,
      replay,
      refresh,
      refreshValues,
      streamingContent,
      streamingNode,
    } = useRun(threadId);
    const [rightTab, setRightTab] = useState<"detail" | "reader">("detail");
    // 就地编辑当前 state 的抽屉开关（暂停点手动纠偏 → 继续）
    const [editorOpen, setEditorOpen] = useState(false);
    // 提示词进化抽屉开关（把人工打回意见提炼进本书提示词 / 整改库复用）
    const [evolveOpen, setEvolveOpen] = useState(false);

    // 脑爆聊天连续视图：等输入（brainstorm_chat interrupt）或 AI 流式回复（brainstorm_respond）
    // 两态都命中，使 BrainstormChat 跨态持续挂载，输入/滚动态不丢。confirm 步与 gate 走普通表单。
    const interruptType =
      interrupt && typeof interrupt.payload === "object" && interrupt.payload
        ? (interrupt.payload as { type?: string }).type
        : undefined;
    // 仅聊天循环（chat/respond/extract/extract_review）命中连续视图；gate 与 extract_review interrupt 走抽屉表单。
    // 注意：extract_review interrupt 到来时 interruptType 会切到 BRAINSTORM_EXTRACT_REVIEW（不匹配这里的
    // BRAINSTORM_CHAT），右侧会自动切到 InterruptHandler 承载抽屉；running 期覆盖只是为了避免
    // brainstorm_extract → brainstorm_extract_review 中间那一拍 UI 从聊天视图闪到 loading。
    const inBrainstorm =
      interruptType === InterruptType.BRAINSTORM_CHAT ||
      (running &&
        (currentNode === "brainstorm_chat" ||
          currentNode === "brainstorm_respond" ||
          currentNode === "brainstorm_extract" ||
          currentNode === "brainstorm_extract_review" ||
          streamingNode === "brainstorm_respond"));

    // 脑爆 AI 回复的流式打字机门控：running 中、有增量内容、且非 extract 节点即显示。
    //
    // 不强绑 streamingNode === "brainstorm_respond" 精确匹配——回复期间 streamingNode 常被
    // 上一拍 brainstorm_chat 的 updates 事件占着，精确匹配会一直 false，导致 token 在
    // streamingContent 里累积却从不渲染（最终只在 refresh 后以历史气泡整段出现）。
    // 用 streamingNode 显式排除 extract（其产出是 JSON，不该进聊天气泡）。
    //
    // ⚠️ 刻意**不**加 !streamingFinalized 闸门（曾试过，会引入空白 bug）：
    // brainstorm_respond 节点内 LLM 流完（finalized=true）后，若历史超过 _KEEP_MESSAGES，
    // 还会跑 _compress（~10s，backend 内部调用，已用 tags=["nostream"] 屏蔽 chunks）。
    // 这期间节点未 return，history 尚未更新。若在 finalized 时立刻隐藏流式气泡，用户会
    // 看到「气泡消失 → 空白 10s → 相同内容以 history 形式冒出」。
    // 交接给 history 的正确判断是「内容相等」，见 BrainstormChat 里的 streamingShown 派生：
    //   streaming && !(lastEntry.role === "ai" && lastEntry.content === streamingContent)
    // history 落地那一刻自动接管，不依赖 finalized 时序。
    const brainstormStreaming =
      running &&
      streamingContent.length > 0 &&
      streamingNode !== "brainstorm_extract";

    // 所有「会 resume 本 thread」的输入（中断表单的确认通过 / 脑爆发送）统一的禁用闸：
    // 本地 running 之外，再叠加 summary 轮询的 busy（同 thread_id 后端正忙）。本地 running 只
    // 覆盖「本实例发起的 run」，挡不住后台 run 或陈旧 UI；summaryBusy 是权威的服务端信号，
    // 二者取或，避免对同一 thread_id 重复触发导致混乱。busy 轮询有 ≤3s 滞后，宁可多禁一会儿。
    const inputDisabled = running || !!summaryBusy;

    // 暴露 replay / continueRun 给 App（左侧「历史」面板「从此点重跑」、小说列表「▶」）
    useImperativeHandle(
      ref,
      () => ({ replay, continueRun }),
      [replay, continueRun]
    );

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

    // 自动继续（列表「▶」入口）：等 pendingResume 出现（首次快照拉回 & 判定为 pending）后触发一次。
    // 命中条件确保不会跟真中断/正在跑冲突；触发后立即通知 App consume 标记，避免 refresh 抖动重复触发。
    useEffect(() => {
      if (
        autoContinue &&
        pendingResume &&
        !interrupt &&
        !running &&
        !loading &&
        !summaryBusy
      ) {
        onAutoContinueConsumed?.();
        void continueRun();
      }
    }, [
      autoContinue,
      pendingResume,
      interrupt,
      running,
      loading,
      summaryBusy,
      continueRun,
      onAutoContinueConsumed,
    ]);

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
            schemaError={graphError}
            onRetrySchema={onRetryGraph}
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
              hasPowerSystem={!!state.has_power_system}
              onHasPowerSystemChange={async (v) => {
                // 就地 update_state：LangGraph 会清 interrupts 两源但保留 next；用 refreshValues
                // 只刷 values 不动内存 interrupt，聊天页 interrupt 表单不消失。
                await updateThreadState(threadId, { has_power_system: v });
                await refreshValues();
              }}
              disabled={inputDisabled}
            />
          ) : interrupt ? (
            <div className="p-4">
              {/* 暂停点入口：进化提示词（仅章节正文/弧线大纲阶段，提炼本次打回意见即生效）/
                  手动纠正当前 state 后再「通过 / 提交意见」继续。进化按钮不受 inputDisabled
                  约束——它只读写 overrides/台账，不 resume 本 thread。 */}
              {state.novel_name && (
                <div className="mb-3 flex justify-end gap-2">
                  {EVOLVABLE_REVIEW_TYPES.has(state.review_type) && (
                    <button
                      type="button"
                      onClick={() => setEvolveOpen(true)}
                      title="把本次打回意见提炼进本书提示词（章节正文 / 弧线大纲阶段下一次生成即生效）"
                      className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:border-blue-300 hover:text-blue-600"
                    >
                      🧬 提示词进化
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setEditorOpen(true)}
                    disabled={inputDisabled}
                    title={inputDisabled ? "运行中不可编辑状态" : undefined}
                    className="rounded border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:border-blue-300 hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-500"
                  >
                    ✎ 编辑当前状态
                  </button>
                </div>
              )}
              {/* 闸由 summary busy 触发、而非本地运行：陈旧 UI / 后台 run 正在跑同一 thread，
                  解释为何「确认通过」等被锁，避免看上去像坏掉。本地 running 期另有流式提示，不重复。 */}
              {summaryBusy && !running && (
                <div className="mb-3 flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                  该小说后台正在处理中，操作已暂时锁定，请稍候…
                </div>
              )}
              <InterruptHandler
                payload={interrupt.payload}
                onSubmit={(value) => void resume(value)}
                disabled={inputDisabled}
                novelState={state}
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
                  {/* pending 提示条：无 interrupt + 无活跃 run + next 非空（重启后卡住）。
                      不自动 continue，显式按钮，避免刷新即消耗算力，也便于用户看清「下一步是啥」。 */}
                  {pendingResume && (
                    <div className="mx-4 mt-3 flex flex-col gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                      <div className="flex items-center gap-2">
                        <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
                        <span>
                          上次运行在
                          <code className="mx-1 rounded bg-amber-100 px-1 py-0.5 font-mono text-[11px]">
                            {pendingResume}
                          </code>
                          处中断，可能是服务重启造成的。
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => void continueRun()}
                        disabled={inputDisabled}
                        className="self-start rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:bg-amber-300"
                      >
                        继续执行
                      </button>
                    </div>
                  )}
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
                  <div className="flex gap-2 px-4 pb-4">
                    {state.novel_name && (
                      <button
                        onClick={() => setEditorOpen(true)}
                        disabled={inputDisabled}
                        title={inputDisabled ? "运行中不可编辑状态" : undefined}
                        className="flex-1 rounded border border-gray-300 px-4 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                      >
                        ✎ 编辑当前状态
                      </button>
                    )}
                    {state.novel_name && (
                      <button
                        onClick={() => setEvolveOpen(true)}
                        className="flex-1 rounded border border-gray-300 px-4 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
                      >
                        🧬 提示词进化
                      </button>
                    )}
                    <button
                      onClick={() => void refresh()}
                      className="flex-1 rounded border border-gray-300 px-4 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
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

        {/* 就地编辑 state 抽屉：暂停点手动纠偏。保存后只刷新 values（refreshValues），
            不动 interrupt——update_state 会清空中断源，跑常规 refresh 会让中断表单消失。 */}
        <StateEditPanel
          open={editorOpen}
          threadId={threadId}
          state={state}
          disabled={inputDisabled}
          onClose={() => setEditorOpen(false)}
          onSaved={refreshValues}
        />

        {/* 提示词进化抽屉：作用域为本书，写入 prompt_overrides.json 的 evolved_directives，下一章生效。 */}
        <PromptEvolutionModal
          open={evolveOpen}
          novelName={state.novel_name}
          genre={state.genre}
          reviewType={state.review_type}
          prefillFeedback={latestHumanFeedback(state)}
          onClose={() => setEvolveOpen(false)}
        />
      </>
    );
  }
);
