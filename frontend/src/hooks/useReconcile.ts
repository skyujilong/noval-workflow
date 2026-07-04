// 整理消解：把本书累积的「历史整改要点」整理成去重、无矛盾的自洽全集。
// 两步：预览（LLM 生成整理结果，可编辑）→ 应用（整段 REPLACE，记 reconcile 事件，可还原）。
// 只负责整理消解这一件事；台账刷新交由外部 onApplied 回调（本 hook 不持有台账）。

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
  open: boolean,
  onApplied: () => Promise<void> | void
): UseReconcile {
  const [preview, setPreview] = useState<ReconcilePreview | null>(null);
  const [edited, setEdited] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 关闭抽屉时清掉上一轮的预览草稿与提示，避免下次打开残留。
  useEffect(() => {
    if (open) return;
    setPreview(null);
    setEdited("");
    setStatus(null);
    setError(null);
  }, [open]);

  const run = useCallback(async () => {
    setPreviewing(true);
    setError(null);
    setStatus(null);
    try {
      const p = await reconcilePreview(novelName, genre);
      setPreview(p);
      setEdited(p.after);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setPreviewing(false);
    }
  }, [novelName, genre]);

  const apply = useCallback(async () => {
    if (!preview || !edited.trim()) return;
    setApplying(true);
    setError(null);
    try {
      await applyReconciled(novelName, genre, {
        text: edited.trim(),
        before: preview.before,
        summary: preview.summary,
      });
      setStatus("已写入整理后的整改，下一章生成即生效");
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
