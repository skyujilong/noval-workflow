// LangGraph 平台 API 客户端封装。
// 后端是 `langgraph dev`（默认 :8123）。MVP 阶段无认证、本地单用户。
//
// 关键约定：
// - 一个「小说」= 一个 thread，novel_name 存在 thread.metadata 里。
// - assistant 通过 graph_id === "noval_workflow" 选取（langgraph.json 配置）。
// - interrupt 检测：run 结束后查 threads.getState().tasks[].interrupts，非空即处于中断。

import { Client } from "@langchain/langgraph-sdk";
import type { NovelState } from "./types";

// 平台 API 地址：优先用环境变量，默认直连本地 langgraph dev（端口与 dev-backend.sh 一致）。
// （直连而非走 vite 代理，避免 SSE 流在代理层出问题；langgraph dev 默认允许 localhost 跨域。）
// VITE_LANGGRAPH_PORT 和 VITE_LANGGRAPH_API_URL 由 vite.config.ts 从 .env/.env.local 读取并注入。
const langgraphPort = (import.meta.env.VITE_LANGGRAPH_PORT as string | undefined) ?? "28123";
const defaultApiUrl = `http://127.0.0.1:${langgraphPort}`;
export const API_URL =
  (import.meta.env.VITE_LANGGRAPH_API_URL as string | undefined) ?? defaultApiUrl;

// langgraph.json 中配置的 graph 名
const GRAPH_ID = "noval_workflow";

export const client = new Client({ apiUrl: API_URL });

// ── Thread（小说）相关类型 ─────────────────────────────────────────────────────

export interface ThreadMeta {
  novel_name?: string;
  created_at?: string;
  status?: "in_progress" | "completed" | "paused";
  // 平台 Metadata 要求可索引；保留已知字段的同时允许任意附加键
  [key: string]: unknown;
}

export interface ThreadInfo {
  thread_id: string;
  metadata: ThreadMeta;
  created_at: string;
  updated_at: string;
  status: string; // idle | busy | error | interrupted 等
  values: Partial<NovelState>;
}

// ── Assistant ─────────────────────────────────────────────────────────────────

let _assistantId: string | null = null;

/** 取默认 assistant（graph_id === noval_workflow）。langgraph dev 启动后会有一个。 */
export async function getAssistantId(): Promise<string> {
  if (_assistantId) return _assistantId;
  const assistants = await client.assistants.search({ limit: 100 });
  const found = assistants.find((a) => a.graph_id === GRAPH_ID) ?? assistants[0];
  if (!found) {
    throw new Error(
      `未找到 graph_id=${GRAPH_ID} 的 assistant，请确认 langgraph dev 已启动。`
    );
  }
  _assistantId = found.assistant_id;
  return _assistantId;
}

// ── Thread CRUD ───────────────────────────────────────────────────────────────

/** 列出所有小说（thread），按更新时间倒序。 */
export async function listThreads(): Promise<ThreadInfo[]> {
  const threads = await client.threads.search({ limit: 200 });
  return threads.map((t) => ({
    thread_id: t.thread_id,
    metadata: (t.metadata ?? {}) as ThreadMeta,
    created_at: t.created_at,
    updated_at: t.updated_at,
    status: t.status as string,
    values: (t.values ?? {}) as Partial<NovelState>,
  }));
}

/** 新建小说（thread）。metadata 暂留空，等 collect_user_inputs 完成后回填 novel_name。 */
export async function createThread(): Promise<ThreadInfo> {
  const t = await client.threads.create({
    metadata: { status: "in_progress" } as ThreadMeta,
  });
  return {
    thread_id: t.thread_id,
    metadata: (t.metadata ?? {}) as ThreadMeta,
    created_at: t.created_at,
    updated_at: t.updated_at,
    status: t.status as string,
    values: (t.values ?? {}) as Partial<NovelState>,
  };
}

/** 回填 thread 的 metadata（如 novel_name）。 */
export async function updateThreadMeta(
  threadId: string,
  metadata: ThreadMeta
): Promise<void> {
  await client.threads.update(threadId, { metadata });
}

/** 删除小说（thread）。 */
export async function deleteThread(threadId: string): Promise<void> {
  await client.threads.delete(threadId);
}

/** 获取 thread 当前 state（含 values 与 tasks/interrupts）。 */
export async function getThreadState(threadId: string) {
  return client.threads.getState(threadId);
}

/** 获取 thread 的 checkpoint 历史（用于回溯）。 */
export async function getThreadHistory(threadId: string, limit = 100) {
  return client.threads.getHistory(threadId, { limit });
}

/**
 * 从某个 checkpoint 分叉出新 thread（time travel）。
 * SDK 的 threads.create 未暴露 checkpoint 字段，但平台 REST API 的 POST /threads 支持
 * { checkpoint: { thread_id, checkpoint_id } }，这里直接 fetch 调用。
 */
export async function forkThread(
  sourceThreadId: string,
  checkpointId: string,
  metadata?: ThreadMeta
): Promise<ThreadInfo> {
  const res = await fetch(`${API_URL}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      checkpoint: { thread_id: sourceThreadId, checkpoint_id: checkpointId },
      metadata: metadata ?? { status: "in_progress" },
    }),
  });
  if (!res.ok) {
    throw new Error(`分叉失败 (${res.status})：${await res.text()}`);
  }
  const t = (await res.json()) as {
    thread_id: string;
    metadata?: ThreadMeta;
    created_at: string;
    updated_at: string;
    status: string;
    values?: Partial<NovelState>;
  };
  return {
    thread_id: t.thread_id,
    metadata: (t.metadata ?? {}) as ThreadMeta,
    created_at: t.created_at,
    updated_at: t.updated_at,
    status: t.status,
    values: (t.values ?? {}) as Partial<NovelState>,
  };
}

// ── 提示词覆盖（按小说，覆盖题材风味字段）────────────────────────────────────
// 走自定义 HTTP 路由（src/http_app.py），直连 API_URL（与 forkThread/章节静态读取一致）。
// 存储不入 langgraph state，编辑后即时生效、对历史回放也生效。

export interface PromptOverridesResponse {
  defaults: Record<string, string>; // 题材默认值（用于预填）
  overrides: Record<string, string>; // 已存覆盖（仅含与默认不同的字段）
}

/** 拉取某小说的题材默认值（供预填）与已存覆盖。 */
export async function getPromptOverrides(
  novelName: string,
  genre: string
): Promise<PromptOverridesResponse> {
  const url = `${API_URL}/prompt-overrides?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`读取提示词覆盖失败 (${res.status})：${await res.text()}`);
  }
  return (await res.json()) as PromptOverridesResponse;
}

/** 保存某小说的提示词覆盖（仅传与默认不同的字段；空对象=全部回退默认）。 */
export async function savePromptOverrides(
  novelName: string,
  overrides: Record<string, string>
): Promise<void> {
  const url = `${API_URL}/prompt-overrides?novel=${encodeURIComponent(novelName)}`;
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });
  if (!res.ok) {
    throw new Error(`保存提示词覆盖失败 (${res.status})：${await res.text()}`);
  }
}

// ── Run（执行 / 恢复）─────────────────────────────────────────────────────────

export type StreamEvent =
  | { event: "metadata"; data: unknown }
  | { event: "values"; data: Partial<NovelState> }
  | { event: "updates"; data: Record<string, unknown>; node: string }
  | { event: "message_chunk"; data: { content: string }; node: string }
  | { event: "end"; data: unknown }
  | { event: "error"; data: unknown };

/** 共享的 streamMode 配置 */
export const STREAM_MODES = ["updates", "values", "messages-tuple"] as const;

/**
 * 从 BaseMessage 中提取文本内容
 * 兼容 content 为 string 或 Array<{type: "text", text: string}> 格式
 */
function extractMessageContent(msg: Record<string, unknown>): string {
  const content = msg?.content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content) && content.length > 0) {
    const first = content[0];
    if (first && typeof first === "object" && "text" in first) {
      return String(first.text ?? "");
    }
  }
  return "";
}

/**
 * 处理 runStream/replayFromCheckpoint 的流式 chunk（数组格式 [event, data]）
 * 统一事件解析逻辑，消除代码重复
 */
export function processStreamChunk(
  chunk: unknown,
  onEvent: (e: StreamEvent) => void
): void {
  // 防御式编程：处理 null/undefined/非数组 chunk（避免 "chunk is not iterable" 崩溃）
  // LangGraph SDK 在网络波动、连接重置、特殊控制帧时可能返回异常 chunk
  if (!chunk || !Array.isArray(chunk) || chunk.length < 2) {
    onEvent({ event: "metadata", data: { invalidChunk: chunk } });
    return;
  }

  const [event, data] = chunk as [string, unknown];
  if (event === "updates") {
    const d = data as Record<string, unknown>;
    const node = Object.keys(d ?? {})[0] ?? "";
    onEvent({ event: "updates", data: d, node });
  } else if (event === "values") {
    onEvent({ event: "values", data: (data ?? {}) as Partial<NovelState> });
  } else if (event === "metadata") {
    onEvent({ event: "metadata", data });
  } else if (event === "error") {
    onEvent({ event: "error", data });
  } else if (event === "messages") {
    // messages-tuple 模式下返回 [BaseMessage, metadata]
    // 同样防御式处理 data 不是数组的情况
    if (!data || !Array.isArray(data) || data.length < 2) {
      onEvent({ event: "metadata", data: { invalidMessagesData: data } });
      return;
    }
    const [msg, meta] = data as [Record<string, unknown>, Record<string, unknown>];
    const content = extractMessageContent(msg);
    const node = (meta?.node as string) || "";
    if (content.length > 0) {
      onEvent({ event: "message_chunk", data: { content }, node });
    }
  } else {
    // 未知事件类型不静默丢弃，转发给上层
    onEvent({ event: "metadata", data: { unknownEvent: event, raw: data } });
  }
}

/**
 * 处理 joinStream 的流式 chunk（对象格式 {event, data}）
 * 统一事件解析逻辑，消除代码重复
 */
export function processJoinStreamChunk(
  chunk: unknown,
  onEvent: (e: StreamEvent) => void
): void {
  // 防御式编程：处理 null/undefined/非对象 chunk（避免崩溃）
  if (!chunk || typeof chunk !== "object") {
    onEvent({ event: "metadata", data: { invalidChunk: chunk } });
    return;
  }

  const c = chunk as { event?: string; data?: unknown };
  // 确保 event 字段存在
  if (!c.event) {
    onEvent({ event: "metadata", data: { missingEvent: chunk } });
    return;
  }

  const event = c.event;
  const data = c.data;

  if (event === "updates") {
    const d = (data ?? {}) as Record<string, unknown>;
    const node = typeof d === "object" && d ? Object.keys(d)[0] ?? "" : "";
    onEvent({ event: "updates", data: d, node });
  } else if (event === "values") {
    onEvent({ event: "values", data: (data ?? {}) as Partial<NovelState> });
  } else if (event === "metadata") {
    onEvent({ event: "metadata", data });
  } else if (event === "error") {
    onEvent({ event: "error", data });
  } else if (event === "messages") {
    // 防御式处理 data 不是数组的情况
    if (!data || !Array.isArray(data) || data.length < 2) {
      onEvent({ event: "metadata", data: { invalidMessagesData: data } });
      return;
    }
    const [msg, meta] = data as [Record<string, unknown>, Record<string, unknown>];
    const content = extractMessageContent(msg);
    const node = (meta?.node as string) || "";
    if (content.length > 0) {
      onEvent({ event: "message_chunk", data: { content }, node });
    }
  } else {
    // 未知事件类型不静默丢弃
    onEvent({ event: "metadata", data: { unknownEvent: event, raw: data } });
  }
}

/**
 * 启动一次 run 并流式消费事件。
 * - 不传 resumeValue：新启动 run（input=null 从 START 开始；新 thread 会立刻在 collect_user_inputs 中断）。
 * - 传 resumeValue：从中断点恢复，使用 Command(resume=...)。
 *
 * 流模式用 updates（拿当前执行节点）+ values（拿状态快照）。
 */
export async function runStream(
  threadId: string,
  onEvent: (e: StreamEvent) => void,
  opts?: { resumeValue?: unknown; input?: Record<string, unknown> | null }
): Promise<void> {
  const assistantId = await getAssistantId();
  const streamRes = client.runs.stream(threadId, assistantId, {
    input: opts?.input ?? null,
    command: opts?.resumeValue !== undefined ? { resume: opts.resumeValue } : undefined,
    streamMode: STREAM_MODES,
  });

  for await (const chunk of streamRes) {
    processStreamChunk(chunk, onEvent);
  }
  onEvent({ event: "end", data: null });
}

/** 列出 thread 的活跃 run（status=running 或 pending）。用于页面刷新后检测后台仍在运行的 LLM。 */
export async function listActiveRuns(threadId: string) {
  const runs = await client.runs.list(threadId, { limit: 10 });
  return runs.filter((r) => r.status === "running" || r.status === "pending");
}

/** 加入已有 run 的流式输出，等待其完成。用于页面刷新后重新连接正在运行的 run。 */
export async function joinRunStream(
  threadId: string,
  runId: string,
  onEvent: (e: StreamEvent) => void
): Promise<void> {
  const stream = client.runs.joinStream(threadId, runId, {
    streamMode: STREAM_MODES,
    cancelOnDisconnect: false,
  });
  for await (const chunk of stream) {
    processJoinStreamChunk(chunk, onEvent);
  }
  onEvent({ event: "end", data: null });
}

/**
 * 从指定 checkpoint 重跑（replay）：同线程，input=null + checkpointId。
 * 后续节点重新执行（LLM 调用、interrupt 都会再次触发），旧历史成为孤儿分支。
 */
export async function replayFromCheckpoint(
  threadId: string,
  checkpointId: string,
  onEvent: (e: StreamEvent) => void
): Promise<void> {
  const assistantId = await getAssistantId();
  const streamRes = client.runs.stream(threadId, assistantId, {
    input: null,
    // SDK 1.9.25 的 runs.stream 只映射 payload.checkpoint，不映射顶层 checkpointId
    // （checkpointId 仍在类型里但运行时被静默丢弃，导致请求体缺 checkpoint_id → 退化成
    // 从最新检查点恢复，历史节点重跑不生效）。必须传 checkpoint 对象；顶层命名空间为 ""。
    checkpoint: { checkpoint_ns: "", checkpoint_id: checkpointId },
    streamMode: STREAM_MODES,
  });

  for await (const chunk of streamRes) {
    processStreamChunk(chunk, onEvent);
  }
  onEvent({ event: "end", data: null });
}

// ── Interrupt 提取 ────────────────────────────────────────────────────────────

export interface CurrentInterrupt {
  /** interrupt payload（即 Python 端 interrupt({...}) 传入的对象） */
  payload: unknown;
  /** 所在 task 的节点名（可能含子图路径，仅作展示参考） */
  nodeName: string;
}

/**
 * 从 thread state 的 tasks 中提取当前待处理的中断。
 * LangGraph 在 interrupt() 处暂停后，getState().tasks[].interrupts 非空。
 * 返回第一个可恢复的中断；无中断返回 null（表示流程已结束或正在运行）。
 *
 * payload 自描述（带 type + 业务上下文），前端无需再读嵌套子图 state。
 */
export function extractInterrupt(state: {
  tasks?: Array<{ name?: string; interrupts?: Array<{ value?: unknown; resumable?: boolean }> }>;
}): CurrentInterrupt | null {
  const tasks = state.tasks ?? [];
  for (const t of tasks) {
    const interrupts = t.interrupts ?? [];
    for (const it of interrupts) {
      if (it.resumable !== false) {
        return { payload: it.value, nodeName: t.name ?? "" };
      }
    }
  }
  return null;
}

// ── Graph 结构（节点图可视化）──────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  name: string;
  type?: string;
  data?: Record<string, unknown>;
}
export interface GraphEdge {
  source: string;
  target: string;
  conditional?: boolean;
}

export async function getGraphSchema(): Promise<{
  nodes: GraphNode[];
  edges: GraphEdge[];
}> {
  const assistantId = await getAssistantId();
  // xray=false：只取顶层节点。顶层节点名与流式 updates 事件的 node 名一致，
  // 便于「当前执行节点」高亮匹配；子图内部结构在顶层以单个节点表示，视图更清晰。
  const g = (await client.assistants.getGraph(assistantId, {
    xray: false,
  })) as { nodes: GraphNode[]; edges: GraphEdge[] };
  return { nodes: g.nodes ?? [], edges: g.edges ?? [] };
}
