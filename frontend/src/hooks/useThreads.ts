// 小说（thread）列表管理：列出 / 新建 / 选择 / 删除。
// 3s 自动轮询更新列表状态，页面后台时暂停。

import { useCallback, useEffect, useRef, useState } from "react";
import { createThread, deleteThread, listThreads, type ThreadInfo } from "../lib/langgraph";

const POLL_INTERVAL = 3000;

export function useThreads() {
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchingRef = useRef(false);

  const refresh = useCallback(async () => {
    // 竞态防护：防止并发请求
    if (fetchingRef.current) return;
    fetchingRef.current = true;

    setLoading(true);
    setError(null);
    try {
      const list = await listThreads();
      // 按 updated_at 倒序
      list.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
      setThreads(list);
    } catch (e) {
      setError(`加载小说列表失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
      fetchingRef.current = false;
    }
  }, []);

  // 首次加载
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 自动轮询：3s 一次，页面后台时暂停 + 竞态防护
  useEffect(() => {
    const doRefresh = () => {
      // 页面后台或正在请求中跳过
      if (document.hidden || fetchingRef.current) return;
      void refresh();
    };

    const timer = setInterval(doRefresh, POLL_INTERVAL);
    const onVisibilityChange = () => {
      // 切回前台时立即刷新一次
      if (!document.hidden) void refresh();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refresh]);

  const create = useCallback(async (): Promise<ThreadInfo | null> => {
    try {
      const t = await createThread();
      await refresh();
      return t;
    } catch (e) {
      setError(`新建小说失败：${(e as Error).message}`);
      return null;
    }
  }, [refresh]);

  const delete_ = useCallback(async (threadId: string): Promise<boolean> => {
    try {
      await deleteThread(threadId);
      await refresh();
      return true;
    } catch (e) {
      setError(`删除小说失败：${(e as Error).message}`);
      return false;
    }
  }, [refresh]);

  return { threads, loading, error, refresh, create, delete: delete_ };
}
