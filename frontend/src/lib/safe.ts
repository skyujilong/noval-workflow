/** 把 LLM 漂移出的 dict/list/null 兜底渲染成字符串——最后一道防御，避免直接塞进 JSX 触发
 * "Objects are not valid as a React child" 崩页。
 *
 * 使用场景：所有会把 draft/state 里"契约上是 str 但可能被 LLM 出成 dict"的字段直接渲染
 * 到 JSX 的位置——Row/FieldCell/纯文本行。后端 subgraph.generate 已在 pydantic 层校验+回喂
 * 让 LLM 修正；但老 checkpoint 里可能已有脏数据、且极小概率 LLM 三次重试仍失败，前端仍需
 * 这道保护避免整个 workspace 崩。
 *
 * 与 String(v) 的区别：String({}) === "[object Object]"，用户看不到内容；这里对对象/数组
 * 用 JSON.stringify 保留可见性，让用户能一眼看出"LLM 把字段拆成对象了"。
 */
export function safeStr(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "[unrenderable]";
  }
}
