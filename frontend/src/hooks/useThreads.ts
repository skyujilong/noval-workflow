// 小说（thread）列表管理：列出 / 新建 / 选择。

import { useCallback, useEffect, useState } from "react";
import { createThread, listThreads, type ThreadInfo } from "../lib/langgraph";

export function useThreads() {
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
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
    }
  }, []);

  useEffect(() => {
    void refresh();
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

  return { threads, loading, error, refresh, create };
}
