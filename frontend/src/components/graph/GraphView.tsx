// React Flow 节点图可视化。按 Phase 分列布局，当前执行节点高亮。

import { useMemo } from "react";
import { ReactFlow, Background, Controls, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphNode } from "../../lib/langgraph";
import { layoutGraph, phaseOf } from "./layout";

interface Props {
  schemaNodes: GraphNode[];
  schemaEdges: { source: string; target: string; conditional?: boolean }[];
  currentNode: string;
  /** 图结构拉取错误信息（三次自动重试全失败后）—— 有值时显示错误态而非"加载中…" */
  schemaError?: string | null;
  /** 手动重试图结构拉取 —— 与 useGraphSchema 的 refetch 对接 */
  onRetrySchema?: () => void;
}

const PHASE_COLOR: Record<string, string> = {
  p0: "#a855f7",
  p1: "#3b82f6",
  p25: "#22c55e",
  p2: "#f97316",
  review: "#ef4444",
  other: "#6b7280",
};

// 骨架节点：不含高亮样式，仅描述"节点长什么样"的稳定形态。
// 拆出来是为了在 currentNode 高频变化时，其他非高亮节点的引用保持稳定 —— React Flow
// 内部按 node.id + 引用做 diff，引用不变就不重渲染该节点。
type BaseRfNode = {
  id: string;
  name: string;
  position: { x: number; y: number };
  data: { label: string };
  /** 未高亮态的完整 style；命中 currentNode 时会用新 style 覆盖，其他节点直接复用 */
  baseStyle: Record<string, string | number>;
  /** 高亮态用到的主色，避免 render 期再查 map */
  color: string;
};

export function GraphView({ schemaNodes, schemaEdges, currentNode, schemaError, onRetrySchema }: Props) {
  // 骨架层：只依赖 schema。schema 由 App 一次性拉取，几乎永不重算 → 骨架引用长期稳定。
  const { baseNodes, rfEdges } = useMemo(() => {
    const layout = layoutGraph(schemaNodes, schemaEdges);
    const baseNodes: BaseRfNode[] = layout.nodes.map((n) => {
      const color = PHASE_COLOR[n.phase] ?? "#6b7280";
      return {
        id: n.id,
        name: n.name,
        position: { x: n.x, y: n.y },
        data: { label: n.name === "__start__" ? "START" : n.name === "__end__" ? "END" : n.name },
        baseStyle: {
          border: `2px solid ${color}`,
          background: "#fff",
          color: "#374151",
          borderRadius: 8,
          padding: "6px 10px",
          fontSize: 12,
          fontWeight: 400,
          boxShadow: "none",
        },
        color,
      };
    });
    const rfEdges = layout.edges.map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: e.conditional ? "smoothstep" : "default",
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: e.conditional ? "#9ca3af" : "#6b7280", strokeDasharray: e.conditional ? "4 2" : undefined },
    }));
    return { baseNodes, rfEdges };
  }, [schemaNodes, schemaEdges]);

  // 高亮层：只对匹配 currentNode 的节点换新对象，其他节点直接复用骨架引用（不 new）。
  // 这样脑爆阶段 currentNode 高频抖动时，React Flow 内部 diff 只处理 ≤2 个节点（旧/新高亮），
  // 而不是把整个 nodes 数组当"全部重建"处理 —— 后者累积到某次会让节点 DOM 丢失（本 bug 根因）。
  const rfNodes = useMemo(() => {
    return baseNodes.map((n) => {
      const isActive = n.name === currentNode || n.id === currentNode;
      if (!isActive) {
        // 关键：非高亮节点整个对象引用稳定复用骨架，才能让 React Flow 判定"未变化"
        return {
          id: n.id,
          position: n.position,
          data: n.data,
          style: n.baseStyle,
        };
      }
      return {
        id: n.id,
        position: n.position,
        data: n.data,
        style: {
          border: `2px solid ${n.color}`,
          background: n.color,
          color: "#fff",
          borderRadius: 8,
          padding: "6px 10px",
          fontSize: 12,
          fontWeight: 700,
          boxShadow: `0 0 0 4px ${n.color}55`,
        },
      };
    });
  }, [baseNodes, currentNode]);

  if (schemaNodes.length === 0) {
    // 三次自动重试全失败：显式错误 + 手动重试；避免用户一直看到"加载中…"无法确认状态
    if (schemaError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
          <div className="text-sm font-medium text-red-600">图结构加载失败</div>
          <div className="max-w-xs break-words text-xs text-gray-500">{schemaError}</div>
          {onRetrySchema && (
            <button
              type="button"
              onClick={onRetrySchema}
              className="mt-1 rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
            >
              重试
            </button>
          )}
        </div>
      );
    }
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        图结构加载中…
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      fitView
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={16} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

// 重新导出 phaseOf 供外部按 phase 着色判断（若需要）
export { phaseOf };
