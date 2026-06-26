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
}

const PHASE_COLOR: Record<string, string> = {
  p0: "#a855f7",
  p1: "#3b82f6",
  p25: "#22c55e",
  p2: "#f97316",
  review: "#ef4444",
  other: "#6b7280",
};

export function GraphView({ schemaNodes, schemaEdges, currentNode }: Props) {
  const { rfNodes, rfEdges } = useMemo(() => {
    const layout = layoutGraph(schemaNodes, schemaEdges);
    const rfNodes = layout.nodes.map((n) => {
      const isActive = n.name === currentNode || n.id === currentNode;
      const color = PHASE_COLOR[n.phase] ?? "#6b7280";
      return {
        id: n.id,
        position: { x: n.x, y: n.y },
        data: { label: n.name === "__start__" ? "START" : n.name === "__end__" ? "END" : n.name },
        style: {
          border: `2px solid ${color}`,
          background: isActive ? color : "#fff",
          color: isActive ? "#fff" : "#374151",
          borderRadius: 8,
          padding: "6px 10px",
          fontSize: 12,
          fontWeight: isActive ? 700 : 400,
          boxShadow: isActive ? `0 0 0 4px ${color}55` : "none",
        },
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
    return { rfNodes, rfEdges };
  }, [schemaNodes, schemaEdges, currentNode]);

  if (schemaNodes.length === 0) {
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
