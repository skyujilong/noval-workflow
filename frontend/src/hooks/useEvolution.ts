// 本书提示词进化：加载事件台账、提炼一条修改意见为提案、应用选中项、还原已应用事件。
// 只负责「本书进化」这一块数据逻辑；整改库相关在 useDirectiveLibrary。

import { useCallback, useEffect, useState } from "react";
import {
  applyPromptEvolution,
  distillPromptEvolution,
  getPromptEvolution,
  restorePromptEvolution,
  type EvolutionEvent,
  type EvolutionProposal,
} from "../lib/langgraph";

/** 提案 + 是否勾选采纳（text 可就地编辑）。 */
export interface ProposalDraft extends EvolutionProposal {
  selected: boolean;
}

interface UseEvolution {
  events: EvolutionEvent[];
  feedback: string;
  setFeedback: (v: string) => void;
  proposals: ProposalDraft[];
  toggleProposal: (index: number) => void;
  editProposalText: (index: number, text: string) => void;
  distilling: boolean;
  applying: boolean;
  /** 提炼：不传＝用顶部输入框新建一条；传台账记录＝就地提炼、把提案更新进该记录。 */
  distill: (sourceEvent?: EvolutionEvent) => Promise<void>;
  /** 批量提炼：把多条打回记录的意见合并成一条上下文，一次提炼出综合去重的提案（新建一条）。 */
  distillBatch: (events: EvolutionEvent[]) => Promise<void>;
  /** 载入某条已提炼记录的提案到操作区（勾选后应用）。 */
  loadEvent: (event: EvolutionEvent) => void;
  apply: () => Promise<void>;
  restore: (eventId: string) => Promise<void>;
  /** 重新拉取台账（供整理消解等外部写入后刷新事件列表）。 */
  refresh: () => Promise<void>;
  status: string | null;
  error: string | null;
}

export function useEvolution(
  novelName: string,
  genre: string,
  reviewType: string,
  prefillFeedback: string,
  open: boolean
): UseEvolution {
  const [events, setEvents] = useState<EvolutionEvent[]>([]);
  const [feedback, setFeedback] = useState("");
  const [proposals, setProposals] = useState<ProposalDraft[]>([]);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [distilling, setDistilling] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshEvents = useCallback(async () => {
    if (!novelName) return;
    try {
      setEvents(await getPromptEvolution(novelName));
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }, [novelName]);

  // 打开时：加载台账 + 用最近一次打回意见预填来源框，重置上一轮的提案/提示。
  useEffect(() => {
    if (!open || !novelName) return;
    setFeedback(prefillFeedback);
    setProposals([]);
    setActiveEventId(null);
    setStatus(null);
    setError(null);
    void refreshEvents();
  }, [open, novelName, prefillFeedback, refreshEvents]);

  // 提炼落地的公共尾巴：调接口 → 载入提案到操作区 → 刷新台账。distill/distillBatch 复用。
  const commitDistilled = useCallback(
    async (
      input: { feedback: string; review_type?: string; event_id?: string },
      describe: (event: EvolutionEvent, summary: string) => string
    ) => {
      setDistilling(true);
      setError(null);
      setStatus(null);
      try {
        const { event, summary } = await distillPromptEvolution(novelName, genre, input);
        setActiveEventId(event.id);
        setProposals(event.proposals.map((p) => ({ ...p, selected: true })));
        setStatus(describe(event, summary));
        await refreshEvents();
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setDistilling(false);
      }
    },
    [novelName, genre, refreshEvents]
  );

  const distill = useCallback(
    async (sourceEvent?: EvolutionEvent) => {
      // 来源：台账某条打回记录（就地提炼、更新该记录）或顶部输入框（新建一条）。
      const fb = (sourceEvent?.source_feedback ?? feedback).trim();
      if (!fb) return;
      await commitDistilled(
        {
          feedback: fb,
          review_type: sourceEvent?.review_type ?? reviewType,
          event_id: sourceEvent?.id,
        },
        (event, summary) =>
          event.proposals.length
            ? `已提炼 ${event.proposals.length} 条整改${summary ? `：${summary}` : ""}`
            : "未提炼出可用整改（可换更具体的意见再试）"
      );
    },
    [feedback, reviewType, commitDistilled]
  );

  const distillBatch = useCallback(
    async (events: EvolutionEvent[]) => {
      // 合并多条打回意见为一条上下文，一次提炼出综合去重的提案（新建一条，不带 event_id）。
      const merged = events
        .map((ent, i) => `${i + 1}. ${ent.source_feedback.trim()}`)
        .filter((s) => s.trim())
        .join("\n")
        .trim();
      if (!merged) return;
      await commitDistilled(
        { feedback: merged, review_type: events[0]?.review_type ?? reviewType },
        (event, summary) =>
          event.proposals.length
            ? `已从 ${events.length} 条记录批量提炼出 ${event.proposals.length} 条整改${summary ? `：${summary}` : ""}`
            : "未提炼出可用整改（可换更具体的意见再试）"
      );
    },
    [reviewType, commitDistilled]
  );

  // 把某条已提炼记录的提案载入操作区（勾选 → 应用）。
  const loadEvent = useCallback((event: EvolutionEvent) => {
    setActiveEventId(event.id);
    setProposals(event.proposals.map((p) => ({ ...p, selected: true })));
    setStatus(null);
    setError(null);
  }, []);

  const toggleProposal = useCallback((index: number) => {
    setProposals((prev) =>
      prev.map((p, i) => (i === index ? { ...p, selected: !p.selected } : p))
    );
  }, []);

  const editProposalText = useCallback((index: number, text: string) => {
    setProposals((prev) => prev.map((p, i) => (i === index ? { ...p, text } : p)));
  }, []);

  const apply = useCallback(async () => {
    if (!activeEventId) return;
    const selected = proposals
      .filter((p) => p.selected && p.text.trim())
      .map((p) => ({ field: p.field, text: p.text.trim(), op: p.op }));
    if (!selected.length) {
      setError("请至少勾选一条整改");
      return;
    }
    setApplying(true);
    setError(null);
    try {
      await applyPromptEvolution(novelName, genre, activeEventId, selected);
      setStatus(`已写入 ${selected.length} 条整改，下一章生成即生效`);
      setProposals([]);
      setActiveEventId(null);
      await refreshEvents();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setApplying(false);
    }
  }, [activeEventId, proposals, novelName, genre, refreshEvents]);

  const restore = useCallback(
    async (eventId: string) => {
      setError(null);
      try {
        await restorePromptEvolution(novelName, eventId);
        setStatus("已还原到该事件应用前的提示词");
        await refreshEvents();
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      }
    },
    [novelName, refreshEvents]
  );

  return {
    events,
    feedback,
    setFeedback,
    proposals,
    toggleProposal,
    editProposalText,
    distilling,
    applying,
    distill,
    distillBatch,
    loadEvent,
    apply,
    restore,
    refresh: refreshEvents,
    status,
    error,
  };
}
