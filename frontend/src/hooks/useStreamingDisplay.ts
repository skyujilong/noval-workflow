// 流式展示态：当前节点 + 打字机增量内容。把 StreamEvent 翻译成可渲染的展示态。
// 用 ref 存流式最新值，handleStreamEvent 无依赖也能读到最新，彻底避免 stale closure。

import { useCallback, useRef, useState } from "react";
import type { StreamEvent } from "../lib/langgraph";

export interface UseStreamingDisplay {
  /** 当前执行/待执行的节点名（流式 updates 或快照 next 写入） */
  currentNode: string;
  /** 当前正在输出内容的节点名 */
  streamingNode: string;
  /** LLM 流式输出的增量内容（打字机效果） */
  streamingContent: string;
  /** 处理流式事件（仅 updates / message_chunk；error 事件交由编排层处理） */
  handleStreamEvent: (e: StreamEvent) => void;
  /** 直接设置当前节点（用于快照中断时取 next[0]） */
  setCurrentNode: (node: string) => void;
  /** 启动新 run 前清空增量内容（不动 currentNode，避免 GraphView 高亮闪空） */
  resetStreaming: () => void;
}

export function useStreamingDisplay(): UseStreamingDisplay {
  const [currentNode, setCurrentNode] = useState("");
  const [streamingNode, setStreamingNode] = useState("");
  const [streamingContent, setStreamingContent] = useState("");
  // 流式状态最新值，避免闭包捕获过时状态
  const streamingStateRef = useRef({ node: "", content: "" });

  const handleStreamEvent = useCallback((e: StreamEvent) => {
    if (e.event === "updates") {
      setCurrentNode(e.node);
      // 节点切换时清空流式内容
      if (e.node && e.node !== streamingStateRef.current.node) {
        streamingStateRef.current = { node: e.node, content: "" };
        setStreamingNode(e.node);
        setStreamingContent("");
      }
    } else if (e.event === "message_chunk") {
      // 节点变了先清空再追加，否则累加
      if (e.node && e.node !== streamingStateRef.current.node) {
        streamingStateRef.current = { node: e.node, content: e.data.content };
        setStreamingNode(e.node);
        setStreamingContent(e.data.content);
      } else {
        streamingStateRef.current.content += e.data.content;
        setStreamingContent(streamingStateRef.current.content);
      }
    }
  }, []); // 无外部依赖 — 用 ref 读最新值

  const resetStreaming = useCallback(() => {
    streamingStateRef.current = { node: "", content: "" };
    setStreamingNode("");
    setStreamingContent("");
  }, []);

  return {
    currentNode,
    streamingNode,
    streamingContent,
    handleStreamEvent,
    setCurrentNode,
    resetStreaming,
  };
}
