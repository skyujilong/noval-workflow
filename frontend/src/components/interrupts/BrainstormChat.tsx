// 灵感脑爆连续聊天视图。
// 同时服务三种运行态：等待用户输入（brainstorm_chat interrupt）、AI 多轮回复流式（brainstorm_respond）、
// 结束脑爆的自然语言收尾流式（brainstorm_finalize）。由 NovelWorkspace 在 interrupt↔running 间
// 持续挂载（不加变化的 key），故本组件的本地态（输入框、滚动位置、乐观气泡）跨态保留，聊天体验连续。
//
// 乐观渲染：用户发出消息后，running 期间后端 state.brainstorm_history 尚未刷新回来，
// 用本地 pendingUserMsg 先把这条消息渲染出来；当 history 回填包含它后自动隐藏（派生判断，
// 不依赖时序，避免重复气泡）。
//
// 底部「本作包含独立力量体系」开关：作品级决策承载点。切换时先 optimistic 更新本地态，再 await
// 父层写回 state（updateThreadState + refreshValues，不清 interrupt）；失败则回滚。开关同时
// 影响 AI 引导风格（system prompt 硬规则）与 brainstorm_finalize 抽取时是否保留力量体系正文。

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * 流式内容自动跟随滚动，允许用户主动脱离与恢复。
 *
 * 核心：区分「人 vs 程序」不靠事件监听，而靠**物理方向**——程序化滚动永远是「往下追」
 * （scrollTop → scrollHeight - clientHeight），所以 scroll 事件里检测到 scrollTop 变**小**，
 * 就一定是人（拖滚动条 / 滚轮 / 触摸 / 键盘 PageUp / 惯性滚动，来源不限）。
 *
 * 程序化滚动前置一个 flag，scroll 事件里识别到就跳过——避免自己触发的 scroll 被误判。
 * 这是 use-stick-to-bottom 等主流库的核心思路，实测对亚像素级小距离滑动也天然敏感。
 *
 * 恢复阈值 40px：用户拖回底部附近（距底 <40）视为回到贴底态；不用得太小，方便用户"松手即贴"。
 */
const BOTTOM_THRESHOLD = 40;

function useStickToBottom() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  // 记录上一次 scroll 事件的 scrollTop，供本次比对方向
  const lastScrollTopRef = useRef(0);
  // 程序化滚动标记：followIfSticking / forceStick 前置置 true，下一次 scroll 事件消费并清零
  const programmaticRef = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    lastScrollTopRef.current = el.scrollTop;

    const onScroll = () => {
      const st = el.scrollTop;
      // 程序化滚动：跳过差值判断，只更新基线（否则会误认为自己在"往下滚"从而不影响，但仍需对齐基线）
      if (programmaticRef.current) {
        programmaticRef.current = false;
        lastScrollTopRef.current = st;
        return;
      }
      // 减小 = 人往上滚（阈值 0.5px 抗亚像素抖动，实测 wheel 一次滚 3-10px、拖滚动条 1px+ 都能触发）
      if (st < lastScrollTopRef.current - 0.5) {
        stickToBottomRef.current = false;
      } else if (el.scrollHeight - st - el.clientHeight < BOTTOM_THRESHOLD) {
        // 增大且距底 <40 → 用户拖回或程序推到底 → 恢复贴底
        stickToBottomRef.current = true;
      }
      lastScrollTopRef.current = st;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // 内容变化时调用：仅贴底态生效
  const followIfSticking = useCallback(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    programmaticRef.current = true;
    el.scrollTop = el.scrollHeight;
  }, []);

  // 强制回底并恢复跟随（用户主动发送新消息时调用——发送 = 明确要看新回复）
  const forceStick = useCallback(() => {
    stickToBottomRef.current = true;
    const el = scrollRef.current;
    if (!el) return;
    programmaticRef.current = true;
    el.scrollTop = el.scrollHeight;
  }, []);

  return { scrollRef, followIfSticking, forceStick };
}

interface ChatEntry {
  role: "human" | "ai";
  content: string;
  /** v3 pin 标记：后端 brainstorm_finalize 追加完整版气泡时打上 "finalize_draft"，前端据此在气泡
   *  顶部渲染分隔条「已被驳回的旧整理」提示用户这不是当前状态，只是修改参考锚点。缺省视为普通聊天。 */
  kind?: "chat" | "finalize_draft";
}

interface Props {
  summary: string;
  history: ChatEntry[];
  /** 是否正在流式输出 AI 回复（running 且节点为 brainstorm_respond 或 brainstorm_finalize） */
  streaming: boolean;
  streamingContent: string;
  /** 是否停在 brainstorm_chat interrupt（可发送） */
  awaitingInput: boolean;
  onSend: (msg: string) => void;
  onEnd: () => void;
  /** v2 结束轮完整版确认：停在 brainstorm_finalize_confirm interrupt 时为 true——
   *  在最后一条 AI 气泡下方渲染「使用这份产物 / 返回脑爆继续」两个按钮。
   *  此 interrupt 期间 awaitingInput=false，底部输入区自然禁用（无需额外闸）。 */
  finalizeConfirm: boolean;
  /** 完整版确认按钮回调：由 NovelWorkspace 转成 resume(buildFinalizeConfirm...) */
  onFinalizeConfirm: (action: "use" | "back_to_chat") => void;
  /** 作品级：是否含独立力量体系（来自 state.has_power_system） */
  hasPowerSystem: boolean;
  /** 切换开关时的写回回调（父层负责 updateThreadState + refreshValues）；返回 Promise 便于失败回滚 */
  onHasPowerSystemChange: (v: boolean) => Promise<void>;
  /** 上层 running：运行期禁用所有输入（resume 期 interrupt 仍保留，故必须用此显式禁用） */
  disabled?: boolean;
}

export function BrainstormChat({
  summary,
  history,
  streaming,
  streamingContent,
  awaitingInput,
  onSend,
  onEnd,
  finalizeConfirm,
  onFinalizeConfirm,
  hasPowerSystem,
  onHasPowerSystemChange,
  disabled,
}: Props) {
  const [input, setInput] = useState("");
  const [pendingUserMsg, setPendingUserMsg] = useState("");
  const { scrollRef, followIfSticking, forceStick } = useStickToBottom();

  // 力量体系开关的 optimistic 本地态：切换后立即反映在 UI，await 写回失败则回滚为父层值。
  // 与父层 hasPowerSystem 同步：当父层拉到新 state 后覆盖本地态（幂等，非编辑中不丢已提交值）。
  const [powerSwitch, setPowerSwitch] = useState(hasPowerSystem);
  const [switchSaving, setSwitchSaving] = useState(false);
  useEffect(() => {
    // 父层刷新到新 state 时同步；本地 saving 期间不覆盖（避免和 optimistic 值打架）
    if (!switchSaving) setPowerSwitch(hasPowerSystem);
  }, [hasPowerSystem, switchSaving]);

  // 乐观气泡是否仍需展示：history 末条 human 尚未等于刚发出的消息时展示（派生，免时序依赖）
  const lastHuman = [...history].reverse().find((m) => m.role === "human");
  const pendingShown = !!pendingUserMsg && lastHuman?.content !== pendingUserMsg;

  // 流式气泡是否仍需展示：history 末条 AI 内容尚未等于当前流式累积内容时展示（与 pendingShown 同构，
  // 派生免时序依赖）。修 Bug：SSE 结束瞬间，useRun 的 `await refresh()`（回填 history 含新 AI 回复）
  // 与 `setRunning(false)` 之间存在微任务边界，React 会渲染一次「history 已含新 AI + streaming 仍为
  // true + streamingContent 是完整内容」的中间态 → 同一段 AI 回复同时以 history 气泡 + streaming 气泡
  // 渲染 → 视觉上闪动一下。用派生判断在等价内容落地那一帧立刻隐藏 streaming 气泡，交给 history
  // 气泡接管，彻底绕开对 React 批处理/微任务时序的依赖。
  const lastEntry = history[history.length - 1];
  const streamingShown =
    streaming && !(lastEntry?.role === "ai" && lastEntry.content === streamingContent);

  // 新消息 / 流式增量 / 乐观气泡变化时，仅在"用户仍贴底"时自动跟随；
  // 用户向上滚开脱离后此处 no-op，交给 useStickToBottom 内部监听 scroll 恢复。
  useEffect(() => {
    followIfSticking();
  }, [history, streamingContent, pendingShown, streaming, followIfSticking]);

  const canSend = awaitingInput && !disabled && input.trim().length > 0;

  const handleSend = () => {
    if (!canSend) return;
    const msg = input.trim();
    setPendingUserMsg(msg); // 乐观渲染：running 期间 history 尚未刷新
    setInput("");
    forceStick(); // 用户主动发送 = 明确要看新回复，即使之前已脱离也强制回底并恢复跟随
    onSend(msg);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 发送，Shift+Enter 换行
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 开关切换：optimistic 更新 → await 父层写回；失败回滚。running 期或非 interrupt 期禁用避免竞态。
  const handlePowerSystemToggle = async (next: boolean) => {
    if (switchSaving) return;
    setPowerSwitch(next); // optimistic
    setSwitchSaving(true);
    try {
      await onHasPowerSystemChange(next);
    } catch {
      // 写回失败：回滚为父层最新值（不必显式 setPowerSwitch，saving 结束后 useEffect 自然同步）
    } finally {
      setSwitchSaving(false);
    }
  };

  const inputDisabled = !awaitingInput || !!disabled;
  // 开关比输入更保守：只有停在 chat interrupt 才允许改（running / respond 期禁用避免和后端 state 冲突）
  const switchDisabled = inputDisabled || switchSaving;

  return (
    <div className="flex h-full flex-col">
      {/* 头部 + 状态 */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-800">✨ 灵感脑爆</h3>
        <span className="flex items-center gap-1.5 text-xs text-gray-400">
          {streaming ? (
            <>
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
              AI 正在思考…
            </>
          ) : awaitingInput ? (
            "轮到你了"
          ) : (
            "处理中…"
          )}
        </span>
      </div>

      {/* 消息区（仅此处滚动） */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4"
      >
        {summary && (
          <details className="rounded border border-gray-200 bg-gray-50 p-2 text-xs">
            <summary className="cursor-pointer text-gray-500">
              早期对话概要（已压缩）
            </summary>
            <div className="mt-2 whitespace-pre-wrap text-gray-600">{summary}</div>
          </details>
        )}

        {history.length === 0 && !pendingShown && !streaming && (
          <div className="py-8 text-center text-sm text-gray-400">
            说说你想写一部什么样的小说，或者让 AI 先给你一些方向～
          </div>
        )}

        {(() => {
          // v3 分隔条挂载策略：finalize_draft 条目只在"已被驳回"时才显示「参考旧整理」提示。
          // 判定：finalizeConfirm=true（当前正停在 finalize_confirm interrupt）时，历史里最后一条
          // finalize_draft 是当前候选（还没被驳回，等用户按 use/back），不加分隔条；其余 finalize_draft
          // 一律加分隔条——它们都是历次点了「返回脑爆继续」被驳回的旧稿。
          let lastDraftIdx = -1;
          for (let k = history.length - 1; k >= 0; k--) {
            if (history[k].kind === "finalize_draft") {
              lastDraftIdx = k;
              break;
            }
          }
          return history.map((m, i) => {
            const isDraft = m.kind === "finalize_draft";
            const isCurrentCandidate = finalizeConfirm && i === lastDraftIdx;
            const showRejectedBanner = isDraft && !isCurrentCandidate;
            return (
              <Bubble
                key={i}
                role={m.role}
                content={m.content}
                kind={showRejectedBanner ? "finalize_draft" : "chat"}
              />
            );
          });
        })()}

        {/* 乐观渲染：running 期间展示用户刚发出的消息 */}
        {pendingShown && <Bubble role="human" content={pendingUserMsg} />}

        {/* AI 流式回复气泡 */}
        {streamingShown && <Bubble role="ai" content={streamingContent || "…"} />}

        {/* v2 结束轮完整版确认卡：finalize_confirm interrupt 期间挂在最后一条 AI 气泡下方。
            使用 → 后端纯 python 切分那份 markdown 到 4 字段 → 进 review 面板；
            返回脑爆 → 后端剥掉这条完整版 AI 气泡 + 复位 brainstorm_done → 回聊天。 */}
        {finalizeConfirm && !streamingShown && (
          <FinalizeConfirmCard
            disabled={!!disabled}
            onUse={() => onFinalizeConfirm("use")}
            onBack={() => onFinalizeConfirm("back_to_chat")}
          />
        )}
      </div>

      {/* 力量体系开关（作品级决策，影响 AI 引导 + 抽取保留） */}
      <div className="shrink-0 border-t bg-gray-50/60 px-4 py-2.5">
        <label className="flex cursor-pointer items-start gap-2.5 text-sm">
          <button
            type="button"
            role="switch"
            aria-checked={powerSwitch}
            onClick={() => void handlePowerSystemToggle(!powerSwitch)}
            disabled={switchDisabled}
            className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
              powerSwitch ? "bg-blue-600" : "bg-gray-300"
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            <span
              className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                powerSwitch ? "translate-x-4" : "translate-x-0.5"
              }`}
            />
          </button>
          <div className="flex-1">
            <div className="font-medium text-gray-800">本作包含独立力量体系</div>
            <div className="mt-0.5 text-xs text-gray-500">
              开启 → AI 会主动引导聊清力量来源 / 层级 / 代价；关闭 → 把实力融进世界观即可，不单列。
              {switchSaving && <span className="ml-1 text-blue-500">保存中…</span>}
            </div>
          </div>
        </label>
      </div>

      {/* 输入区（固定底部） */}
      <div className="shrink-0 border-t p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={inputDisabled}
          placeholder={
            awaitingInput
              ? "输入你的想法…（Enter 发送 / Shift+Enter 换行）"
              : "AI 回复中，请稍候…"
          }
          rows={3}
          className="w-full resize-none rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-gray-100"
        />
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={onEnd}
            disabled={inputDisabled}
            className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            结束脑爆
          </button>
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            className="flex-1 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  kind,
}: {
  role: "human" | "ai";
  content: string;
  /** v3：finalize_draft 标记 AI 气泡顶部加分隔条，明确告诉用户这是已被驳回的旧整理。
   *  只对历史条目生效；流式 streamingContent 那条气泡不传 kind，因此正在流的完整版不会
   *  错误地显示"被驳回"标签（那时还没被驳回呢）。 */
  kind?: "chat" | "finalize_draft";
}) {
  if (role === "human") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-sm bg-blue-600 px-3 py-2 text-sm text-white">
          {content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg rounded-bl-sm bg-gray-100 px-3 py-2 text-sm text-gray-800">
        {kind === "finalize_draft" && (
          <div className="mb-2 -mx-3 -mt-2 rounded-t-lg border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
            📋 以下是已被驳回的旧整理，仅供参考修改
          </div>
        )}
        <div className="prose prose-sm max-w-none [&_p]:my-1">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

// v2 结束轮完整版确认卡：贴在最后一条 AI 气泡下方，两个按钮二选一。本地 submitting 状态避免
// 重复点击（父层 disabled 是 running 期通用闸；点击后立即禁用两个按钮直到 interrupt 消费完毕）。
function FinalizeConfirmCard({
  disabled,
  onUse,
  onBack,
}: {
  disabled: boolean;
  onUse: () => void;
  onBack: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const isDisabled = disabled || submitting;
  const handle = (fn: () => void) => {
    setSubmitting(true);
    fn();
  };
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg border border-blue-100 bg-blue-50/60 p-3">
        <div className="mb-2 text-xs text-gray-600">
          👆 上面这份就是即将进入 review 的完整版。整理无误就使用；有想改的就返回聊天继续。
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handle(onUse)}
            disabled={isDisabled}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {submitting ? "⏳ 提交中…" : "✓ 使用这份产物"}
          </button>
          <button
            type="button"
            onClick={() => handle(onBack)}
            disabled={isDisabled}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            ← 返回脑爆继续
          </button>
        </div>
      </div>
    </div>
  );
}
