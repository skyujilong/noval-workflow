// 实体卡「人工删除」的会话状态机：request(卡) → 二次确认 → confirm 落库删除 → 刷新。
//
// 删除是不可逆的带外写卡操作，故走「先请求、再确认」两步，避免误点。逻辑全收在此 hook，
// NovelDetail 只做声明式渲染。thread_id 与刷新回调由父层注入。

import { useCallback, useRef, useState } from "react";
import { deleteEntityCard } from "../lib/langgraph";
import type { EntityCard } from "../lib/types";

export interface UseDeleteEntityCard {
  pending: EntityCard | null; // 等待二次确认的卡；null = 无待确认
  busy: boolean; // 删除请求进行中
  error: string | null;
  request: (card: EntityCard) => void; // 发起删除请求（进入待确认）
  confirm: () => void; // 确认删除（真正落库）
  cancel: () => void; // 取消
}

/**
 * @param threadId 当前小说 thread（带外删卡的目标）
 * @param onDeleted 删除成功回调（父层应 refreshValues 刷新卡库）
 */
export function useDeleteEntityCard(
  threadId: string,
  onDeleted: () => void | Promise<void>
): UseDeleteEntityCard {
  const [pending, setPending] = useState<EntityCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 镜像最新 pending，供异步流程读取，避免 StrictMode 双调 setState updater 里塞副作用。
  const pendingRef = useRef<EntityCard | null>(null);
  pendingRef.current = pending;

  const request = useCallback((card: EntityCard) => {
    setError(null);
    setPending(card);
  }, []);

  const cancel = useCallback(() => {
    setPending(null);
    setError(null);
  }, []);

  const confirm = useCallback(() => {
    const card = pendingRef.current;
    if (!card || busy) return; // 无待确认或已在删除则忽略
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        await deleteEntityCard(threadId, card.name, card.type);
        await onDeleted();
        setPending(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    })();
  }, [threadId, busy, onDeleted]);

  return { pending, busy, error, request, confirm, cancel };
}
