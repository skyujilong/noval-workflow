// 灵感脑爆连续聊天视图。
// 同时服务两种运行态：等待用户输入（brainstorm_chat interrupt）与 AI 流式回复（brainstorm_respond）。
// 由 NovelWorkspace 在 interrupt↔running 间持续挂载（不加变化的 key），故本组件的本地态
// （输入框、滚动位置、乐观气泡）跨态保留，聊天体验连续。
//
// 乐观渲染：用户发出消息后，running 期间后端 state.brainstorm_history 尚未刷新回来，
// 用本地 pendingUserMsg 先把这条消息渲染出来；当 history 回填包含它后自动隐藏（派生判断，
// 不依赖时序，避免重复气泡）。

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
  disabled,
}: Props) {
  const [input, setInput] = useState("");
  const [pendingUserMsg, setPendingUserMsg] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

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

  const inputDisabled = !awaitingInput || !!disabled;

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
