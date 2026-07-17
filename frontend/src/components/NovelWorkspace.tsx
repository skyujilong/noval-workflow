// 单本小说运行时容器：由 App 以 key={threadId} 渲染，切换小说时整树重挂载，
// 故每本小说一个独立 useRun 实例，跨小说隔离由 React 协调天然保证（无需手写守卫）。
// 渲染中部节点图 + 右侧「中断表单 / 流式 / 小说详情」，并自管运行相关的副作用：
//   - autoStart：因「新建」挂载时自动启动 run
//   - 回填：collect_user_inputs 完成后把 novel_name 写回 thread metadata
//   - 状态上报：把 currentNode/running/error 上报给 App 渲染 header / 错误条
//   - replay：经 ref 暴露给 App 左侧「历史」面板

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { GraphView } from "./graph/GraphView";
import { InterruptHandler } from "./interrupts/InterruptHandler";
import { LazyModeSwitch, LongPlanAutoSwitch } from "./interrupts/LazyModeSwitch";
import { BrainstormChat } from "./interrupts/BrainstormChat";
import { ChapterReader } from "./novel/ChapterReader";
import { NovelDetail } from "./novel/NovelDetail";
import { VolumeRibbon } from "./novel/VolumeRibbon";
import { StateEditPanel } from "./state/StateEditPanel";
import { PromptEvolutionModal } from "./novel/PromptEvolutionModal";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "./ui/sheet";
import { useRun } from "../hooks/useRun";
import { useLazyAutoResume } from "../hooks/useLazyAutoResume";
import { isPreWritingInterrupt } from "../lib/lazyMode";
import { updateThreadMeta, updateThreadState } from "../lib/langgraph";
import type { GraphEdge, GraphNode, ThreadMeta } from "../lib/langgraph";
import {
  BRAINSTORM_END,
  InterruptType,
  buildFinalizeConfirmBackToChat,
  buildFinalizeConfirmUse,
} from "../lib/interruptTypes";
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
  /** 自动模式开关（全局偏好，App 持有 + localStorage 持久化） */
  lazyMode: boolean;
  /** 切换自动模式 */
  onLazyModeChange: (next: boolean) => void;
  /** 「长线规划自动化」子开关（默认关=遇长线规划停回人工，防剧情偏移） */
  autoLongPlan: boolean;
  /** 切换长线规划自动化 */
  onAutoLongPlanChange: (next: boolean) => void;
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
      lazyMode,
      onLazyModeChange,
      autoLongPlan,
      onAutoLongPlanChange,
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
    // 章节阅读抽屉开关（右上角常驻按钮触发，任意阶段可随时回看已生成正文）
    const [readerOpen, setReaderOpen] = useState(false);
    // back_to_chat 转换桥接：用户点击「返回脑爆」后，在 setRunning(false) 与
    // setInterrupt(BRAINSTORM_CHAT) 之间的渲染间隙保持 inBrainstorm=true，避免闪烁旧抽屉。
    const transitioningToChatRef = useRef(false);

    // 脑爆聊天连续视图：等输入（brainstorm_chat interrupt）或 AI 流式回复（brainstorm_respond）
    // 或结束轮完整版确认（brainstorm_finalize_confirm interrupt）
    // 三态都命中，使 BrainstormChat 跨态持续挂载，输入/滚动态不丢。confirm 步与 gate 走普通表单。
    const interruptType =
      interrupt && typeof interrupt.payload === "object" && interrupt.payload
        ? (interrupt.payload as { type?: string }).type
        : undefined;
    // 聊天循环（chat/respond/finalize/finalize_confirm/extract_review）命中连续视图；
    // gate 与 extract_review interrupt 走抽屉表单。
    // brainstorm_finalize 现改回**可视流式**（v2 保真度改造：LLM 输出的完整版 markdown 会以 AI 气泡打字机
    // 效果流到聊天页），故 streamingNode 白名单里加回它；currentNode 也保留在覆盖列表里避免过渡拍闪烁。
    // finalize_confirm interrupt 也归本视图——按钮渲染在聊天页 AI 气泡下方，不走 InterruptHandler。
    const inBrainstorm =
      interruptType === InterruptType.BRAINSTORM_CHAT ||
      interruptType === InterruptType.BRAINSTORM_FINALIZE_CONFIRM ||
      transitioningToChatRef.current ||
      (running &&
        (currentNode === "brainstorm_chat" ||
          currentNode === "brainstorm_respond" ||
          currentNode === "brainstorm_finalize" ||
          currentNode === "brainstorm_finalize_confirm" ||
          currentNode === "brainstorm_extract_review" ||
          streamingNode === "brainstorm_respond" ||
          streamingNode === "brainstorm_finalize"));

    // 脑爆 AI 回复的流式打字机门控：running 中、有增量内容、且流式节点是 brainstorm_respond
    // （多轮对话中间的正常回复）或 brainstorm_finalize（v2 结束轮生成完整版 markdown）。
    //
    // brainstorm_finalize 现在走**可视流式**（无 nostream tag）——LLM 整理的完整版 markdown 会
    // 增量流到 AI 气泡末尾，让用户能亲眼看到即将变成 review 内容的原文。流完后节点会 return
    // 到 finalize_confirm interrupt，前端 pipeline：running → 落库到 history → interrupt payload 到位，
    // 中间那一拍靠 BrainstormChat 的 streamingShown 派生自动接管，不闪烁。
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
      (streamingNode === "brainstorm_respond" ||
        streamingNode === "brainstorm_finalize");

    // 所有「会 resume 本 thread」的输入（中断表单的确认通过 / 脑爆发送）统一的禁用闸：
    // 本地 running 之外，再叠加 summary 轮询的 busy（同 thread_id 后端正忙）。本地 running 只
    // 覆盖「本实例发起的 run」，挡不住后台 run 或陈旧 UI；summaryBusy 是权威的服务端信号，
    // 二者取或，避免对同一 thread_id 重复触发导致混乱。busy 轮询有 ≤3s 滞后，宁可多禁一会儿。
    const inputDisabled = running || !!summaryBusy;

    // 中断表单的统一 resume 入口：手动提交与自动模式自动应答共用这一条路径，
    // 天然不会双份逻辑；并发去重再由 useRun 的 runningRef + inputDisabled 兜底。
    const handleInterruptSubmit = useCallback(
      (value: unknown) => {
        if (
          typeof value === "object" &&
          value !== null &&
          "action" in value &&
          (value as { action: string }).action === "back_to_chat"
        ) {
          transitioningToChatRef.current = true;
        }
        void resume(value);
      },
      [resume]
    );

    // 自动模式：进入可自动应答的中断先 5s 倒计时，到点自动走 handleInterruptSubmit
    const lazy = useLazyAutoResume({
      interrupt,
      enabled: lazyMode,
      autoLongPlan,
      inputDisabled,
      onAutoResume: handleInterruptSubmit,
    });

    // 是否已进入章节写作阶段：开写前（脑爆/初始参数/一致性冻结/设定 review）禁用自动模式开关。
    // 无 interrupt 时（running/detail 态）本行不参与渲染——开关只在 interrupt 分支下展示。
    const inWritingStage = !!interrupt && !isPreWritingInterrupt(interrupt.payload);

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

    // back_to_chat 转换结束：interruptType 离开 EXTRACT_REVIEW（切到 BRAINSTORM_CHAT 成功）或出错时清除桥接标记
    useEffect(() => {
      if (interruptType !== InterruptType.BRAINSTORM_EXTRACT_REVIEW || error) {
        transitioningToChatRef.current = false;
      }
    }, [interruptType, error]);

    // collect_user_inputs 完成后，把 novel_name 回填到 thread metadata
    useEffect(() => {
      if (!state.novel_name || threadMeta?.novel_name) return;
      void updateThreadMeta(threadId, { ...threadMeta, novel_name: state.novel_name });
      onRefreshThreads();
    }, [threadId, state.novel_name, threadMeta, onRefreshThreads]);

    return (
      <>
        {/* 中部：节点图 */}
        <main className="relative flex-1 bg-gray-50">
          <GraphView
            schemaNodes={graphNodes}
            schemaEdges={graphEdges}
            currentNode={currentNode}
            schemaError={graphError}
            onRetrySchema={onRetryGraph}
          />
          {/* 自动模式倒计时：悬浮在节点图上（不插进右侧表单 DOM，避免出现/消失时表单跳动）。
              到点自动应答；可「立即执行」或「手动接管」（取消本次自动）。 */}
          {lazy.active && lazy.plan && (
            <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-4">
              <div className="pointer-events-auto w-full max-w-md rounded-lg border border-amber-300 bg-amber-50/95 px-3 py-2 shadow-lg backdrop-blur">
                <div className="flex items-center justify-between text-xs text-amber-800">
                  <span>
                    ⚡ 自动模式：{lazy.plan.actionLabel} ·{" "}
                    {Math.ceil(lazy.remainingMs / 1000)}s 后自动执行
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={lazy.fireNow}
                      className="rounded bg-amber-600 px-2 py-1 text-white hover:bg-amber-700"
                    >
                      立即执行
                    </button>
                    <button
                      type="button"
                      onClick={lazy.cancel}
                      className="rounded border border-amber-400 px-2 py-1 text-amber-700 hover:bg-amber-100"
                    >
                      手动接管
                    </button>
                  </div>
                </div>
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded bg-amber-200">
                  <div
                    className="h-full bg-amber-500 transition-[width] duration-100 ease-linear"
                    style={{ width: `${(lazy.remainingMs / lazy.totalMs) * 100}%` }}
                  />
                </div>
              </div>
            </div>
          )}
        </main>

        {/* 右侧：中断表单 / 流式 / 小说详情（顺序刻意保留：resume 期保留旧中断表单） */}
        <aside className="relative flex-1 overflow-y-auto border-l bg-white">
          {/* 顶部横条：左＝分卷大结构（横向滚动，volumes 空则左侧留空），右＝常驻「阅读章节」入口。
              sticky 吸顶、跨 interrupt/running/detail 所有态可见/可点——分卷一眼可见，正文随时回看。
              novel_name 空（脑爆前期）时整条不渲染（此时 volumes 也必空，等价旧 VolumeRibbon 的 null）。 */}
          {state.novel_name && (
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-gray-200 bg-gray-50/95 px-3 py-1.5 backdrop-blur">
              <div className="min-w-0 flex-1">
                <VolumeRibbon state={state} />
              </div>
              <button
                type="button"
                onClick={() => setReaderOpen(true)}
                title="阅读已生成的章节正文（任意阶段可随时查看）"
                className="shrink-0 rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-500 hover:border-blue-300 hover:text-blue-600"
              >
                📖 阅读章节
              </button>
            </div>
          )}
          {inBrainstorm ? (
            <BrainstormChat
              summary={state.brainstorm_summary ?? ""}
              history={state.brainstorm_history ?? []}
              streaming={brainstormStreaming}
              streamingContent={streamingContent}
              awaitingInput={interruptType === InterruptType.BRAINSTORM_CHAT}
              onSend={(m) => void resume(m)}
              onEnd={() => void resume(BRAINSTORM_END)}
              // v2 结束轮：finalize_confirm interrupt 到达时，聊天页在最后一条 AI 气泡下方渲染两个按钮，
              // 输入框此期间禁用（awaitingInput=false 已经覆盖，此 prop 是让按钮显示）。
              finalizeConfirm={interruptType === InterruptType.BRAINSTORM_FINALIZE_CONFIRM}
              onFinalizeConfirm={(action) =>
                void resume(
                  action === "use"
                    ? buildFinalizeConfirmUse()
                    : buildFinalizeConfirmBackToChat()
                )
              }
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
              {/* 顶部同一行：左侧「自动模式」开关（常驻、可随时开关），右侧暂停点入口
                  （进化提示词：仅章节正文/弧线大纲阶段，提炼本次打回意见即生效；编辑当前状态：
                  手动纠正 state 后再「通过 / 提交意见」继续）。进化按钮不受 inputDisabled
                  约束——它只读写 overrides/台账，不 resume 本 thread。 */}
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-4">
                  <LazyModeSwitch
                    checked={lazyMode}
                    onChange={onLazyModeChange}
                    disabled={!inWritingStage}
                  />
                  {/* 长线规划子开关：仅自动模式开启且已进入写作阶段时展示 */}
                  {lazyMode && inWritingStage && (
                    <LongPlanAutoSwitch
                      checked={autoLongPlan}
                      onChange={onAutoLongPlanChange}
                    />
                  )}
                </div>
                {state.novel_name && (
                  <div className="flex gap-2">
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
              </div>
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
                onSubmit={handleInterruptSubmit}
                disabled={inputDisabled}
                novelState={state}
                threadId={threadId}
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
                  <NovelDetail state={state} threadId={threadId} onPromoted={refreshValues} />
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
                // 详情 tab 里在可滚动面板中，给一层固定高度承载 ChapterReader 的 h-full
                <div className="h-[70vh]">
                  <ChapterReader state={state} />
                </div>
              )}
            </>
          )}
        </aside>

        {/* 章节阅读抽屉：右上角常驻按钮触发，复用 ChapterReader（左列表右正文）。
            与右侧详情 tab 同一组件，但以抽屉呈现，故任意阶段（含中断/生成中）都能打开回看。 */}
        <Sheet open={readerOpen} onOpenChange={setReaderOpen}>
          {/* flex-col：header 固定高、ChapterReader 占满剩余（min-h-0 让内部两列能各自滚动） */}
          <SheetContent side="right" className="flex flex-col gap-0 p-0">
            <SheetHeader className="border-b px-4 py-3 text-left">
              <SheetTitle>📖 阅读章节</SheetTitle>
            </SheetHeader>
            <div className="min-h-0 flex-1">
              <ChapterReader state={state} />
            </div>
          </SheetContent>
        </Sheet>

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
