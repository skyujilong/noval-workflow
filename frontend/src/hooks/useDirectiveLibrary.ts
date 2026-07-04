// 题材整改库：按题材/关键词查询、勾选导入本书；以及「从本书精炼入库」（拆条→勾选→入库）。

import { useCallback, useEffect, useState } from "react";
import {
  commitLibraryItems,
  importLibraryItems,
  listLibrary,
  refineToLibrary,
  type DirectiveItem,
  type RefinedCandidate,
} from "../lib/langgraph";

/** 精炼候选 + 是否勾选入库（text 可就地编辑）。 */
export interface CandidateDraft extends RefinedCandidate {
  selected: boolean;
}

interface UseDirectiveLibrary {
  items: DirectiveItem[];
  loading: boolean;
  query: string;
  setQuery: (v: string) => void;
  showAll: boolean;
  setShowAll: (v: boolean) => void;
  reload: () => Promise<void>;
  selectedIds: Set<string>;
  toggleSelect: (id: string) => void;
  importing: boolean;
  importSelected: () => Promise<void>;
  candidates: CandidateDraft[];
  toggleCandidate: (index: number) => void;
  editCandidateText: (index: number, text: string) => void;
  refining: boolean;
  committing: boolean;
  refine: () => Promise<void>;
  commit: () => Promise<void>;
  status: string | null;
  error: string | null;
}

export function useDirectiveLibrary(
  novelName: string,
  genre: string,
  open: boolean
): UseDirectiveLibrary {
  const [items, setItems] = useState<DirectiveItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);
  const [candidates, setCandidates] = useState<CandidateDraft[]>([]);
  const [refining, setRefining] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listLibrary(genre, query.trim(), showAll));
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setLoading(false);
    }
  }, [genre, query, showAll]);

  // 打开、题材/全部切换、搜索词变化时重查（搜索用 300ms 防抖）。
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => void reload(), 300);
    return () => clearTimeout(t);
  }, [open, reload]);

  // 关闭后清空一次性态，避免下次打开残留。
  useEffect(() => {
    if (open) return;
    setCandidates([]);
    setSelectedIds(new Set());
    setStatus(null);
  }, [open]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const importSelected = useCallback(async () => {
    if (!selectedIds.size) return;
    setImporting(true);
    setError(null);
    try {
      const { imported } = await importLibraryItems(novelName, genre, [...selectedIds]);
      setStatus(
        imported > 0
          ? `已导入 ${imported} 条到本书，下一章生成即生效`
          : "选中的条目均已存在，无新增"
      );
      setSelectedIds(new Set());
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setImporting(false);
    }
  }, [selectedIds, novelName, genre]);

  const refine = useCallback(async () => {
    setRefining(true);
    setError(null);
    setStatus(null);
    try {
      const cands = await refineToLibrary(novelName, genre);
      setCandidates(cands.map((c) => ({ ...c, selected: true })));
      setStatus(cands.length ? `已精炼出 ${cands.length} 条候选` : "本书暂无可精炼的历史整改");
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setRefining(false);
    }
  }, [novelName, genre]);

  const toggleCandidate = useCallback((index: number) => {
    setCandidates((prev) =>
      prev.map((c, i) => (i === index ? { ...c, selected: !c.selected } : c))
    );
  }, []);

  const editCandidateText = useCallback((index: number, text: string) => {
    setCandidates((prev) => prev.map((c, i) => (i === index ? { ...c, text } : c)));
  }, []);

  const commit = useCallback(async () => {
    const chosen = candidates
      .filter((c) => c.selected && c.text.trim())
      .map((c) => ({ title: c.title, text: c.text.trim(), tags: c.tags }));
    if (!chosen.length) {
      setError("请至少勾选一条候选");
      return;
    }
    setCommitting(true);
    setError(null);
    try {
      const saved = await commitLibraryItems(genre, chosen, novelName);
      setStatus(`已入库 ${saved.length} 条`);
      setCandidates([]);
      await reload();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setCommitting(false);
    }
  }, [candidates, genre, novelName, reload]);

  return {
    items,
    loading,
    query,
    setQuery,
    showAll,
    setShowAll,
    reload,
    selectedIds,
    toggleSelect,
    importing,
    importSelected,
    candidates,
    toggleCandidate,
    editCandidateText,
    refining,
    committing,
    refine,
    commit,
    status,
    error,
  };
}
