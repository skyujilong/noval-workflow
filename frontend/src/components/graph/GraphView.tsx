// React Flow 节点图可视化。按 Phase 分列布局，当前执行节点高亮。
//
// 关键实现：uncontrolled + useReactFlow().updateNode() 局部 patch 高亮
// ------------------------------------------------------------------
// 曾经用 controlled 模式（`<ReactFlow nodes={rfNodes}>` 每次 currentNode 变都新数组），
// 结果是 React Flow 内部 store 的 `measured` 字段被外部 nodes 覆盖丢失 —— React Flow
// 对未测量节点会加 `visibility:hidden` 避免用户看到未定位的节点，正常场景下 ResizeObserver
// 一帧后就 measure 好、visibility 恢复；但脑爆阶段 `updates` 事件高频推进 currentNode，
// 每次都抹掉 measured，ResizeObserver 追不上就会累积卡在 hidden。DOM 上表现是"背景在、
// 47 个节点都在但全部 visibility:hidden"，切走切回（组件 remount）内部 store 重置才恢复。
//
// 官方推荐的解法是 uncontrolled：`defaultNodes` 挂载时一次性喂进去、之后 measured 由
// React Flow 内部自管；高亮切换用 `useReactFlow().updateNode(id, {style})` 局部 patch，
// 只影响该 id 一个节点，其他节点连同 measured 一起保留。本组件节点是纯只读（不允许拖拽/
// 选择/连线），不需要外部维护 nodes state，uncontrolled 语义最贴。
//
// schema 更新（refetch 成功）时通过 key={schemaVersion} 让 Inner 整个 remount 重读
// defaultNodes —— schema 由 App 一次性拉取，几乎不变，remount 成本可忽略。

import { useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MarkerType,
  useReactFlow,
} from "@xyflow/react";
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
  pm1: "#d946ef",
  p0: "#a855f7",
  p1: "#3b82f6",
  p25: "#22c55e",
  p2: "#f97316",
  review: "#ef4444",
  other: "#6b7280",
};

// 骨架节点：不含高亮样式，仅描述"节点长什么样"的稳定形态。
// name 保留是因为 currentNode 可能是节点 name 或 id，二者都得能匹配。
type BaseRfNode = {
  id: string;
  name: string;
  position: { x: number; y: number };
  data: { label: string };
  baseStyle: Record<string, string | number>;
  /** 高亮态用到的主色 */
  color: string;
};

/** 高亮样式 —— 抽出来是为了 Inner 里 patch 时和还原时用同一份定义 */
function highlightStyle(color: string): Record<string, string | number> {
  return {
    border: `2px solid ${color}`,
    background: color,
    color: "#fff",
    borderRadius: 8,
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 700,
    boxShadow: `0 0 0 4px ${color}55`,
  };
}

function baseStyle(color: string): Record<string, string | number> {
  return {
    border: `2px solid ${color}`,
    background: "#fff",
    color: "#374151",
    borderRadius: 8,
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 400,
    boxShadow: "none",
  };
}

/** Inner —— 必须挂在 ReactFlowProvider 下，才能用 useReactFlow */
function GraphViewInner({
  baseNodes,
  rfEdges,
  currentNode,
}: {
  baseNodes: BaseRfNode[];
  rfEdges: Array<{
    id: string;
    source: string;
    target: string;
    type: string;
    animated: boolean;
    markerEnd: { type: MarkerType };
    style: { stroke: string; strokeDasharray?: string };
  }>;
  currentNode: string;
}) {
  const { updateNode } = useReactFlow();
  const prevActiveIdRef = useRef<string | null>(null);

  // defaultNodes 只在挂载时读一次；schema 变化通过外层 key 触发 remount 让这里重算。
  const defaultNodes = useMemo(
    () =>
      baseNodes.map((n) => ({
        id: n.id,
        position: n.position,
        data: n.data,
        style: n.baseStyle,
      })),
    // 只依赖挂载时的 baseNodes，schema 更新走 key 强制 remount
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // currentNode 变化：只 patch 「旧高亮 → 还原」+ 「新高亮 → 上色」，其他节点不动。
  // React Flow 内部按 id 局部更新，不会影响任何一个未涉及节点的 measured 字段。
  useEffect(() => {
    const activeMeta = currentNode
      ? baseNodes.find((n) => n.name === currentNode || n.id === currentNode)
      : undefined;
    const newActiveId = activeMeta?.id ?? null;
    const prevActiveId = prevActiveIdRef.current;

    if (newActiveId === prevActiveId) return;

    // 还原旧高亮
    if (prevActiveId) {
      const prev = baseNodes.find((n) => n.id === prevActiveId);
      if (prev) {
        updateNode(prevActiveId, { style: prev.baseStyle });
      }
    }
    // 上新高亮
    if (newActiveId && activeMeta) {
      updateNode(newActiveId, { style: highlightStyle(activeMeta.color) });
    }
    prevActiveIdRef.current = newActiveId;
  }, [currentNode, baseNodes, updateNode]);

  return (
    <ReactFlow
      defaultNodes={defaultNodes}
      defaultEdges={rfEdges}
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

export function GraphView({
  schemaNodes,
  schemaEdges,
  currentNode,
  schemaError,
  onRetrySchema,
}: Props) {
  // 骨架：只依赖 schema。schema 由 App 一次性拉取，多数情况下引用长期稳定。
  const { baseNodes, rfEdges } = useMemo(() => {
    const layout = layoutGraph(schemaNodes, schemaEdges);
    const baseNodes: BaseRfNode[] = layout.nodes.map((n) => {
      const color = PHASE_COLOR[n.phase] ?? "#6b7280";
      return {
        id: n.id,
        name: n.name,
        position: { x: n.x, y: n.y },
        data: {
          label:
            n.name === "__start__"
              ? "START"
              : n.name === "__end__"
              ? "END"
              : n.name,
        },
        baseStyle: baseStyle(color),
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
      style: {
        stroke: e.conditional ? "#9ca3af" : "#6b7280",
        strokeDasharray: e.conditional ? "4 2" : undefined,
      },
    }));
    return { baseNodes, rfEdges };
  }, [schemaNodes, schemaEdges]);

  // schema 变化时用作 Inner 的 key，触发 remount 重读 defaultNodes。
  // 用节点 id 序列而不是引用相等，防止 layoutGraph 每次返回新数组但内容一致时误 remount。
  const schemaVersion = useMemo(
    () => baseNodes.map((n) => n.id).join("|"),
    [baseNodes]
  );

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
    <ReactFlowProvider>
      <GraphViewInner
        key={schemaVersion}
        baseNodes={baseNodes}
        rfEdges={rfEdges}
        currentNode={currentNode}
      />
    </ReactFlowProvider>
  );
}

// 重新导出 phaseOf 供外部按 phase 着色判断（若需要）
export { phaseOf };
