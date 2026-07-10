// 拉取 graph 结构（节点 + 边）用于 React Flow 渲染。
// 首次失败自带三次固定退避重试（1s / 3s / 6s），避免 langgraph dev 刚启动时前端一次拉不到就
// 卡在"加载中…"永不恢复。三次全失败暴露 error 与 refetch，UI 侧显式提示 + 手动重试。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getGraphSchema,
  type GraphEdge,
  type GraphNode,
} from "../lib/langgraph";

/** 自动重试的退避序列（毫秒），末尾不含首拉本身 */
const RETRY_DELAYS_MS = [1000, 3000, 6000];

export function useGraphSchema(enabled: boolean) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 手动重试的触发器：incr → useEffect 重跑
  const [manualTrigger, setManualTrigger] = useState(0);
  // 存最新 cancelled 引用，供手动 refetch 时提前中止上一轮
  const runIdRef = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const runId = ++runIdRef.current;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const attempt = async (retryIdx: number) => {
      if (runId !== runIdRef.current) return; // 已被更新的 run 顶替，静默丢弃
      setLoading(true);
      try {
        const g = await getGraphSchema();
        if (runId !== runIdRef.current) return;
        setNodes(g.nodes);
        setEdges(g.edges);
        setError(null);
        setLoading(false);
      } catch (e) {
        if (runId !== runIdRef.current) return;
        // 还有重试机会：不动 error（避免闪一下报错），等下一次
        if (retryIdx < RETRY_DELAYS_MS.length) {
          timer = setTimeout(() => attempt(retryIdx + 1), RETRY_DELAYS_MS[retryIdx]);
          return;
        }
        // 重试全部耗尽：暴露 error 供 UI 显式提示
        setError(`加载图结构失败：${(e as Error).message}`);
        setLoading(false);
      }
    };

    void attempt(0);
    return () => {
      // 组件卸载或依赖变化：让本轮 attempt 的后续回调作废
      runIdRef.current++;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, manualTrigger]);

  // 用户可见的手动重试入口：清 error 触发新一轮拉取（含自动重试链）
  const refetch = useCallback(() => {
    setError(null);
    setManualTrigger((v) => v + 1);
  }, []);

  return { nodes, edges, loading, error, refetch };
}
