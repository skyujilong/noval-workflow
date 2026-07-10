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

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";

interface ChatEntry {
  role: "human" | "ai";
  content: string;
}

interface Props {
  summary: string;
  history: ChatEntry[];
  /** 是否正在流式输出 AI 回复（running 且节点为 brainstorm_respond） */
  streaming: boolean;
  streamingContent: string;
  /** 是否停在 brainstorm_chat interrupt（可发送） */
  awaitingInput: boolean;
  onSend: (msg: string) => void;
  onEnd: () => void;
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
  hasPowerSystem,
  onHasPowerSystemChange,
  disabled,
}: Props) {
  const [input, setInput] = useState("");
  const [pendingUserMsg, setPendingUserMsg] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // 新消息 / 流式增量 / 乐观气泡变化时自动滚到底（ref 直接操作，不进 render）
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, streamingContent, pendingShown, streaming]);

  const canSend = awaitingInput && !disabled && input.trim().length > 0;

  const handleSend = () => {
    if (!canSend) return;
    const msg = input.trim();
    setPendingUserMsg(msg); // 乐观渲染：running 期间 history 尚未刷新
    setInput("");
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

        {history.map((m, i) => (
          <Bubble key={i} role={m.role} content={m.content} />
        ))}

        {/* 乐观渲染：running 期间展示用户刚发出的消息 */}
        {pendingShown && <Bubble role="human" content={pendingUserMsg} />}

        {/* AI 流式回复气泡 */}
        {streamingShown && <Bubble role="ai" content={streamingContent || "…"} />}
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

function Bubble({ role, content }: { role: "human" | "ai"; content: string }) {
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
        <div className="prose prose-sm max-w-none [&_p]:my-1">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
