// 节点图布局：按 Phase 分列排布顶层节点。
// 顶层节点名与流式 updates 事件的 node 名一致，便于高亮当前执行节点。

import type { GraphEdge, GraphNode } from "../../lib/langgraph";

export type PhaseKey = "p0" | "p1" | "p25" | "p2" | "review" | "other";

/** 根据节点名归类到 Phase */
export function phaseOf(name: string): PhaseKey {
  if (name === "__start__" || name === "collect_user_inputs") return "p0";
  // 弧线相关
  if (
    name.includes("arc_outline") ||
    name.startsWith("arc_") ||
    name === "prepare_arc_outline" ||
    name === "save_arc_outline"
  )
    return "p25";
  // 章节写作主链路
  if (
    [
      "prepare_titles",
      "save_titles",
      "prepare_chapter",
      "save_chapter",
      "generate_summary",
      "ask_continue",
      "chapter_edit_subgraph",
    ].includes(name) ||
    name.startsWith("route_")
  )
    return "p2";
  // 审稿子图节点（review_*）
  if (name.startsWith("review_") || name === "review_subgraph") return "review";
  // 基础设定 prepare_/save_/save_config
  if (name.startsWith("prepare_") || name.startsWith("save_")) return "p1";
  if (name === "__end__") return "other";
  return "other";
}

const PHASE_ORDER: PhaseKey[] = ["p0", "p1", "p25", "p2", "review", "other"];
const PHASE_LABEL: Record<PhaseKey, string> = {
  p0: "Phase 0 · 用户输入",
  p1: "Phase 1 · 基础设定",
  p25: "Phase 2.5 · 弧线规划",
  p2: "Phase 2 · 章节写作",
  review: "审稿子图",
  other: "其他",
};

const PHASE_X: Record<PhaseKey, number> = {
  p0: 0,
  p1: 260,
  p25: 520,
  p2: 780,
  review: 1040,
  other: 1040,
};

export interface LayoutedNode {
  id: string;
  name: string;
  phase: PhaseKey;
  x: number;
  y: number;
}

export interface LayoutResult {
  nodes: LayoutedNode[];
  edges: GraphEdge[];
  phaseLabels: { phase: PhaseKey; label: string; x: number }[];
}

/** 按 Phase 分列、列内纵向堆叠的简单布局 */
export function layoutGraph(
  schemaNodes: GraphNode[],
  schemaEdges: GraphEdge[]
): LayoutResult {
  const buckets: Record<PhaseKey, GraphNode[]> = {
    p0: [],
    p1: [],
    p25: [],
    p2: [],
    review: [],
    other: [],
  };
  for (const n of schemaNodes) {
    const name = n.name ?? n.id;
    buckets[phaseOf(name)].push(n);
  }

  const COL_W = 220;
  const ROW_H = 70;
  const nodes: LayoutedNode[] = [];
  for (const phase of PHASE_ORDER) {
    const list = buckets[phase];
    list.forEach((n, i) => {
      const name = n.name ?? n.id;
      nodes.push({
        id: n.id,
        name,
        phase,
        x: PHASE_X[phase] + (i % 2) * (COL_W / 2),
        y: i * ROW_H,
      });
    });
  }

  const phaseLabels = PHASE_ORDER.filter((p) => buckets[p].length > 0).map(
    (p) => ({ phase: p, label: PHASE_LABEL[p], x: PHASE_X[p] })
  );

  return { nodes, edges: schemaEdges, phaseLabels };
}
