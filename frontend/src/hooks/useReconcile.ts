// 整理消解:把本书某桶累积的「历史整改要点」整理成去重、无矛盾的自洽全集。
// 三桶隔离下,reconcile 只作用于当前 review_type 对应的桶。
// 两步:预览(LLM 生成整理结果,可编辑) → 应用(整段 REPLACE 到该桶,记 reconcile 事件,可还原)。

import { useCallback, useEffect, useState } from "react";
import {
  applyReconciled,
  reconcilePreview,
  type ReconcilePreview,
} from "../lib/langgraph";

interface UseReconcile {
  preview: ReconcilePreview | null;
  edited: string;
  setEdited: (v: string) => void;
  previewing: boolean;
  applying: boolean;
  run: () => Promise<void>;
  apply: () => Promise<void>;
  cancel: () => void;
  status: string | null;
  error: string | null;
}

export function useReconcile(
  novelName: string,
  genre: string,
  reviewType: string,
  open: boolean,
  onApplied: () => Promise<void> | void
): UseReconcile {
  const [preview, setPreview] = useState<ReconcilePreview | null>(null);
  const [edited, setEdited] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 关闭抽屉、或切 reviewType 时清掉上一轮的预览草稿与提示,避免残留跨桶数据。
  useEffect(() => {
    setPreview(null);
    setEdited("");
    setStatus(null);
    setError(null);
  }, [open, reviewType]);

  const run = useCallback(async () => {
    setPreviewing(true);
    setError(null);
    setStatus(null);
    try {
      const p = await reconcilePreview(novelName, genre, reviewType);
      setPreview(p);
      setEdited(p.after);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setPreviewing(false);
    }
  }, [novelName, genre, reviewType]);

  const apply = useCallback(async () => {
    if (!preview || !edited.trim()) return;
    setApplying(true);
    setError(null);
    try {
      await applyReconciled(novelName, genre, {
        text: edited.trim(),
        before: preview.before,
        summary: preview.summary,
        review_type: preview.review_type,
        field: preview.field,
      });
      setStatus("已写入整理后的整改,下一次生成即生效");
      setPreview(null);
      setEdited("");
      await onApplied();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setApplying(false);
    }
  }, [preview, edited, novelName, genre, onApplied]);

  const cancel = useCallback(() => {
    setPreview(null);
    setEdited("");
    setStatus(null);
    setError(null);
  }, []);

  return { preview, edited, setEdited, previewing, applying, run, apply, cancel, status, error };
}
