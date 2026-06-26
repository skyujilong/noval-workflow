// 拉取 graph 结构（节点 + 边）用于 React Flow 渲染。

import { useEffect, useState } from "react";
import {
  getGraphSchema,
  type GraphEdge,
  type GraphNode,
} from "../lib/langgraph";

export function useGraphSchema(enabled: boolean) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoading(true);
    getGraphSchema()
      .then((g) => {
        if (cancelled) return;
        setNodes(g.nodes);
        setEdges(g.edges);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(`加载图结构失败：${(e as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { nodes, edges, loading, error };
}
