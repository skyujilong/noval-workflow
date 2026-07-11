// LangGraph 平台 API 客户端封装。
// 后端是 `langgraph dev`（默认 :8123）。MVP 阶段无认证、本地单用户。
//
// 关键约定：
// - 一个「小说」= 一个 thread，novel_name 存在 thread.metadata 里。
// - assistant 通过 graph_id === "noval_workflow" 选取（langgraph.json 配置）。
// - interrupt 检测：run 结束后查 threads.getState().tasks[].interrupts，非空即处于中断。

import { Client, type Checkpoint } from "@langchain/langgraph-sdk";
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
  /** 服务端判定的「等待继续」标记：status=interrupted 但无真中断（interrupts dict 为空），
   *  常见于 langgraph dev 重启后 pending 卡住的场景。前端据此在列表卡片显示「▶」按钮。 */
  pending_resume?: boolean;
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

/** 列出所有小说（thread）。
 *  走自定义轻量接口 GET /novels/summary 而非平台 POST /threads/search：
 *  后者会为每个 thread 返回完整 values（整个 NovelState），3s 轮询下 payload 达数百 KB；
 *  /novels/summary 在服务端把 values 裁成摘要白名单（novel_name/genre/total_chapters_written），
 *  形状与 search 一致，故下面映射逻辑保持不变，仅 values 变小。 */
export async function listThreads(): Promise<ThreadInfo[]> {
  const res = await fetch(`${API_URL}/novels/summary?limit=200`);
  if (!res.ok) {
    throw new Error(`加载小说列表失败 (${res.status})：${await res.text()}`);
  }
  const rows = (await res.json()) as Array<{
    thread_id: string;
    metadata?: ThreadMeta;
    created_at: string;
    updated_at: string;
    status: string;
    values?: Partial<NovelState>;
    pending_resume?: boolean;
  }>;
  return rows.map((t) => ({
    thread_id: t.thread_id,
    metadata: (t.metadata ?? {}) as ThreadMeta,
    created_at: t.created_at,
    updated_at: t.updated_at,
    status: t.status as string,
    values: (t.values ?? {}) as Partial<NovelState>,
    pending_resume: t.pending_resume ?? false,
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

/**
 * 就地修改 thread 当前（最新）checkpoint 的 state（LangGraph 原生 update_state）。
 * 用于「暂停点手动纠正 state → 继续」——只 patch 传入的字段，其余不动。
 *
 * ⚠️ 刻意**不传 asNode**（已实测）：
 * - 不传 → 值写入、`next` 保持在原中断节点、后续 resume 正常恢复并保留改动（正确）。
 * - 传 asNode → LangGraph 把该节点当「已执行」，跳过中断并污染 resume（错误）。
 *
 * ⚠️ 另一个已实测副作用：update_state 后 `tasks[].interrupts` 与顶层 `thread.interrupts`
 * 都会被清空（但 `next` 保留、resume 仍可用）。故调用方保存后**只应刷新 values、保留内存里的
 * interrupt**，切勿跑会 extractInterrupt 的常规 refresh（否则中断表单会消失）。
 *
 * ⚠️ reducer 字段（all_chapter_titles / all_chapter_summaries，operator.add）是**追加**语义，
 * 不要经此覆盖——编辑白名单已将它们排除（见 lib/editableState.ts）。
 */
export async function updateThreadState(
  threadId: string,
  values: Partial<NovelState>
): Promise<void> {
  await client.threads.updateState(threadId, { values });
}

/** 获取 thread 的 checkpoint 历史（用于回溯）。
 *  🔍 关键参数：include_subgraphs = true —— 必须加，否则只返回主图 checkpoint，
 *  子图（chapter_edit、arc_edit 等）的历史会被隐藏，导致历史列表不完整。
 */
export async function getThreadHistory(threadId: string, limit = 100) {
  // include_subgraphs：平台运行时 API 支持，但 SDK 类型未声明该字段，
  // 断言到 SDK 选项类型以绕过多余属性检查（值在运行时仍会被发送）。
  return client.threads.getHistory(threadId, {
    limit,
    include_subgraphs: true,  // 🔐 必须！包含子图 checkpoint，否则子图历史看不到
  } as Parameters<typeof client.threads.getHistory>[1]);
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

// ── 提示词自进化（按小说：提炼/应用/还原）+ 整改库（跨小说：精炼入库/查询/导入）──
// 同样走自定义 HTTP 路由（src/http_app.py），直连 API_URL。台账与整改库在中央 SQLite；
// 应用/导入写入该小说 prompt_overrides.json 的 evolved_directives，下一次生成新鲜读取即生效。

export interface EvolutionProposal {
  field: string;
  op: string; // "append" | "replace"
  text: string;
  rationale: string;
  conflicts_with: string; // 非空＝覆盖某条原规则
}

export interface EvolutionEvent {
  id: string;
  created_at: string;
  novel_name: string;
  genre: string;
  trigger: string; // "manual" | "reject" | "import" | "reconcile"
  review_type: string;
  chapter_index: number | null;
  source_feedback: string;
  rejected_excerpt: string;
  proposals: EvolutionProposal[];
  status: string; // "proposed" | "applied" | "reverted"
  applied: Record<string, string>;
  applied_at: string | null;
  reverted_at: string | null;
}

export interface DirectiveItem {
  id: string;
  created_at: string;
  genre: string;
  title: string;
  text: string;
  tags: string[];
  source_novel: string;
  usage_count: number;
}

/** 精炼拆条的候选（尚未入库） */
export interface RefinedCandidate {
  title: string;
  text: string;
  tags: string[];
}

/** apply 时提交的单条选中整改 */
export interface SelectedDirective {
  field: string;
  text: string;
  op: string; // "append" | "replace"
}

async function postJson<T>(url: string, body: unknown, errLabel: string): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`${errLabel}失败 (${res.status})：${await res.text()}`);
  }
  return (await res.json()) as T;
}

/** 打回时把修改意见自动落一条 REJECT 记录（供进化抽屉逐条提炼）。 */
export async function recordReject(
  novelName: string,
  genre: string,
  input: { review_type: string; feedback: string; chapter_index?: number | null }
): Promise<void> {
  const url = `${API_URL}/prompt-evolution/reject?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  await postJson(url, input, "记录打回");
}

/** 列出某小说的进化事件台账（最新在前）。 */
export async function getPromptEvolution(novelName: string): Promise<EvolutionEvent[]> {
  const res = await fetch(`${API_URL}/prompt-evolution?novel=${encodeURIComponent(novelName)}`);
  if (!res.ok) {
    throw new Error(`读取进化台账失败 (${res.status})：${await res.text()}`);
  }
  const data = (await res.json()) as { events: EvolutionEvent[] };
  return data.events;
}

/** 提炼一条人工修改意见为整改提案（落一条 proposed 事件）。 */
export async function distillPromptEvolution(
  novelName: string,
  genre: string,
  input: {
    feedback: string;
    review_type?: string;
    draft_excerpt?: string;
    chapter_index?: number | null;
    /** 传入则「就地提炼」：把提案更新进该已有记录（打回记录）而非新建。 */
    event_id?: string;
  }
): Promise<{ event: EvolutionEvent; summary: string }> {
  const url = `${API_URL}/prompt-evolution/distill?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  return postJson(url, input, "提炼");
}

/** 应用某事件里选中的整改到该小说覆盖（下一章生效）。 */
export async function applyPromptEvolution(
  novelName: string,
  genre: string,
  eventId: string,
  selected: SelectedDirective[]
): Promise<{ overrides: Record<string, string>; event: EvolutionEvent }> {
  const url = `${API_URL}/prompt-evolution/apply?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  return postJson(url, { event_id: eventId, selected }, "应用整改");
}

/** 把某已应用事件还原到应用前快照。 */
export async function restorePromptEvolution(novelName: string, eventId: string): Promise<void> {
  const url = `${API_URL}/prompt-evolution/restore?novel=${encodeURIComponent(novelName)}`;
  await postJson(url, { event_id: eventId }, "还原");
}

/** 整理消解预览：把累积整改去重、消解矛盾成自洽全集（不落盘，供确认后再应用）。 */
export interface ReconcilePreview {
  before: string;
  after: string;
  summary: string;
  resolved: string[];
}

export async function reconcilePreview(
  novelName: string,
  genre: string
): Promise<ReconcilePreview> {
  const url = `${API_URL}/prompt-evolution/reconcile?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  return postJson(url, {}, "整理消解预览");
}

/** 应用整理后的自洽整改（整段 REPLACE，记一条 reconcile 事件，可还原）。 */
export async function applyReconciled(
  novelName: string,
  genre: string,
  input: { text: string; before: string; summary: string }
): Promise<{ overrides: Record<string, string>; event: EvolutionEvent }> {
  const url = `${API_URL}/prompt-evolution/reconcile/apply?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  return postJson(url, input, "应用整理");
}

/** 把某小说累积的整改精炼拆成候选条目（不落库）。 */
export async function refineToLibrary(
  novelName: string,
  genre: string
): Promise<RefinedCandidate[]> {
  const url = `${API_URL}/prompt-library/refine?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  const data = await postJson<{ items: RefinedCandidate[] }>(url, {}, "精炼");
  return data.items;
}

/** 把选中的候选条目入中央整改库。 */
export async function commitLibraryItems(
  genre: string,
  items: RefinedCandidate[],
  sourceNovel: string
): Promise<DirectiveItem[]> {
  const url = `${API_URL}/prompt-library?genre=${encodeURIComponent(genre)}`;
  const data = await postJson<{ items: DirectiveItem[] }>(
    url,
    { items, source_novel: sourceNovel },
    "入库"
  );
  return data.items;
}

/** 查询整改库（showAll=true 放宽到全部题材）。 */
export async function listLibrary(
  genre: string,
  q: string,
  showAll: boolean
): Promise<DirectiveItem[]> {
  const params = new URLSearchParams();
  if (genre) params.set("genre", genre);
  if (q) params.set("q", q);
  if (showAll) params.set("all", "1");
  const res = await fetch(`${API_URL}/prompt-library?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`查询整改库失败 (${res.status})：${await res.text()}`);
  }
  const data = (await res.json()) as { items: DirectiveItem[] };
  return data.items;
}

/** 把选中的库条目导入某小说的 evolved_directives（去重追加）。 */
export async function importLibraryItems(
  novelName: string,
  genre: string,
  itemIds: string[]
): Promise<{ imported: number }> {
  const url = `${API_URL}/prompt-library/import?novel=${encodeURIComponent(
    novelName
  )}&genre=${encodeURIComponent(genre)}`;
  return postJson(url, { item_ids: itemIds }, "导入");
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
  // ⚠️ 形态归一化（root-cause fix）：
  // @langchain/langgraph-sdk 1.9.25 的 runs.stream()/replay 产出的是 SSE StreamPart 对象
  //   { id, event, data }（与 joinStream 同形），**不是** 旧版的 [event, data] 元组。
  // 旧代码用 `!Array.isArray(chunk)` 当非法 chunk 直接丢弃 → 每一个流式块都被吞掉，
  // message_chunk 事件永不发出，前端打字机自然永不更新（内容只在末尾靠快照 refresh 整段冒出）。
  // 这里两种形态都接：对象取 .event/.data，数组取 [0]/[1]，跨 SDK 版本都稳。
  let event: string | undefined;
  let data: unknown;
  if (Array.isArray(chunk) && chunk.length >= 2) {
    [event, data] = chunk as [string, unknown];
  } else if (chunk && typeof chunk === "object" && "event" in chunk) {
    event = (chunk as { event?: string }).event;
    data = (chunk as { data?: unknown }).data;
  } else {
    onEvent({ event: "metadata", data: { invalidChunk: chunk } });
    return;
  }

  if (event === "updates") {
    const d = (data ?? {}) as Record<string, unknown>;
    const keys = Object.keys(d);
    // 空 updates（如 END 路由信号）：不推进 currentNode，避免图高亮短暂闪空。
    // LangGraph 在图末尾会发一条 `updates {}`，若照旧 setCurrentNode(""), 图高亮消失一帧
    // 再被下一个真事件覆盖回来——观感就是「图闪一下」。转为 metadata（观察用）。
    if (keys.length === 0) {
      onEvent({ event: "metadata", data: { emptyUpdates: d } });
      return;
    }
    onEvent({ event: "updates", data: d, node: keys[0] });
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
    // 节点名取自 messages-tuple metadata 的 `langgraph_node`（LangGraph 标准字段）。
    // 旧代码误读不存在的 `meta.node`，导致每个 message_chunk 的 node 恒为 ""，
    // 依赖精确节点匹配的流式视图（如脑爆 brainstorm_respond 打字机）因此永不激活。
    // 保留 meta.node 作兜底，兼容潜在的非平台来源。
    const node = (meta?.langgraph_node as string) || (meta?.node as string) || "";
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
    const keys = typeof d === "object" && d ? Object.keys(d) : [];
    // 同 processStreamChunk：空 updates 不推进 currentNode，避免图高亮闪空
    if (keys.length === 0) {
      onEvent({ event: "metadata", data: { emptyUpdates: d } });
      return;
    }
    onEvent({ event: "updates", data: d, node: keys[0] });
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
    // 同 processStreamChunk：节点名取 `langgraph_node`，而非不存在的 `meta.node`。
    const node = (meta?.langgraph_node as string) || (meta?.node as string) || "";
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
  opts?: {
    resumeValue?: unknown;
    input?: Record<string, unknown> | null;
    signal?: AbortSignal;
  }
): Promise<void> {
  const assistantId = await getAssistantId();
  const streamRes = client.runs.stream(threadId, assistantId, {
    input: opts?.input ?? null,
    command: opts?.resumeValue !== undefined ? { resume: opts.resumeValue } : undefined,
    streamMode: [...STREAM_MODES],
    // SSE 断线续传：开启后服务端为每个事件分配 event_id 并缓冲。客户端 join 时必须
    // 显式传 Last-Event-ID: "-" 才会从头 replay 全量事件；不传 header，服务端从当前
    // 进度开始推，切走期间产生的 token 全部丢失（官方约定，见
    // docs.langchain.com/langsmith/streaming）。切走再切回、页面刷新等 join 场景由
    // joinRunStream 显式带 lastEventId="-" 触发从头 replay，useStreamingDisplay 在
    // 节点首个 chunk 处清空累加器，天然无内容翻倍。
    streamResumable: true,
    signal: opts?.signal,
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

/**
 * 加入已有 run 的流式输出，等待其完成。用于：
 *   1) 页面刷新后重新连接正在运行的 run
 *   2) 切走 thread 再切回时，重新订阅仍在跑的 run
 *
 * `opts.lastEventId` 传给服务端的 Last-Event-ID header：
 *   - `"-"`（默认，官方约定）：从事件缓冲区头部 replay 全量事件，前端拿到完整流。
 *   - 具体 event id：从该 id 之后开始（用于短断线续传，本项目暂无此路径）。
 *   - `undefined`：SDK 不发 header → 服务端从当前进度开始推（**会丢失历史 token**，勿用）。
 *
 * 前端累加器（useStreamingDisplay）在节点首个 chunk 到达时清空重填，从头 replay
 * 不会导致内容翻倍。参考 SDK 1.9.25 行为：
 *   `node_modules/@langchain/langgraph-sdk/dist/client/runs/index.js:253`
 *   `headers: opts?.lastEventId ? { "Last-Event-ID": opts.lastEventId } : void 0`
 */
export async function joinRunStream(
  threadId: string,
  runId: string,
  onEvent: (e: StreamEvent) => void,
  opts?: { lastEventId?: string; signal?: AbortSignal }
): Promise<void> {
  const stream = client.runs.joinStream(threadId, runId, {
    streamMode: [...STREAM_MODES],
    cancelOnDisconnect: false,
    lastEventId: opts?.lastEventId ?? "-",
    signal: opts?.signal,
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
  onEvent: (e: StreamEvent) => void,
  opts?: { signal?: AbortSignal }
): Promise<void> {
  const assistantId = await getAssistantId();
  const streamRes = client.runs.stream(threadId, assistantId, {
    input: null,
    // SDK 1.9.25 的 runs.stream 只映射 payload.checkpoint，不映射顶层 checkpointId
    // （checkpointId 仍在类型里但运行时被静默丢弃，导致请求体缺 checkpoint_id → 退化成
    // 从最新检查点恢复，历史节点重跑不生效）。必须传 checkpoint 对象；顶层命名空间为 ""。
    // SDK 类型要求 checkpoint_map 等字段，运行时只需 ns + id；断言到 SDK 类型，运行时不变。
    checkpoint: { checkpoint_ns: "", checkpoint_id: checkpointId } as Omit<
      Checkpoint,
      "thread_id"
    >,
    streamMode: [...STREAM_MODES],
    // 与 runStream 一致开启断线续传：replay 出的 run 也需要能在「切走再切回」场景 join 时
    // 从头 replay 全量事件（否则回到中途看到的是残缺流）。
    streamResumable: true,
    signal: opts?.signal,
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

/** 中断条目最小形状（覆盖 tasks[].interrupts 与 threads.get() 顶层 interrupts 两处来源） */
interface RawInterrupt {
  value?: unknown;
  resumable?: boolean;
}

/** getThread 返回的 interrupts 字段形状：{ [task_id]: RawInterrupt[] } */
export type ThreadInterruptsMap = Record<string, RawInterrupt[]>;

/**
 * 从 thread 快照中提取当前待处理的中断。
 *
 * 双数据源合并（root-cause fix）：
 * - 主源 `state.tasks[i].interrupts`：来自 GET /threads/{tid}/state。运行中或刚 pause 时最新。
 * - 兜底 `threadInterrupts`：来自 GET /threads/{tid} 的顶层 interrupts dict（按 task_id 键控）。
 *   在 langgraph dev 进程重启后观察到：state 的 tasks[].interrupts 是空数组，但 thread 表上
 *   的 denormalized interrupts 仍保有完整 payload。仅读主源会误判为「无中断」，导致 UI 卡在
 *   无按钮的空态。用主源的 task.id 反查 dict 兜底，可恢复真中断。
 *
 * 严格用 `task.id → dict[task.id]` 关联；不做 dict.values() 遍历取任意值的模糊兜底，
 * 避免在 task 与 dict 不齐时给出错误的中断（宁可 null 让上层显式处理，也不静默伪装成功）。
 *
 * 返回第一个可恢复的中断；无则返回 null（真正流程结束或运行中）。
 */
export function extractInterrupt(
  state: {
    tasks?: Array<{
      id?: string;
      name?: string;
      interrupts?: RawInterrupt[];
    }>;
  },
  threadInterrupts?: ThreadInterruptsMap | null
): CurrentInterrupt | null {
  const tasks = state.tasks ?? [];
  for (const t of tasks) {
    // 主源：tasks[i].interrupts
    for (const it of t.interrupts ?? []) {
      if (it.resumable !== false) {
        return { payload: it.value, nodeName: t.name ?? "" };
      }
    }
    // 兜底：threadInterrupts[task.id]（重启后主源为空，但顶层 dict 仍在）
    if (t.id && threadInterrupts && Array.isArray(threadInterrupts[t.id])) {
      for (const it of threadInterrupts[t.id]) {
        if (it.resumable !== false) {
          return { payload: it.value, nodeName: t.name ?? "" };
        }
      }
    }
  }
  return null;
}

/**
 * 拉取 thread 的顶层 interrupts 兜底源（对 getState 的补充）。
 * SDK 的 threads.get 返回 { interrupts: { [task_id]: [...] } }。这里显式类型化。
 */
export async function getThreadInterrupts(
  threadId: string
): Promise<ThreadInterruptsMap> {
  const t = (await client.threads.get(threadId)) as {
    interrupts?: ThreadInterruptsMap;
  };
  return t.interrupts ?? {};
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
