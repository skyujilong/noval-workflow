// 本书提示词进化:三桶隔离版。当前打开的 reviewType 决定「看到的世界」——
// 台账/整改提案/整理消解都只作用于当前环节的桶,跨桶分发靠 applies_to 显式勾选。
// 批量提炼产物不再直接进入操作区,而是作为「归纳建议」单独一列,用户采纳后才写入。

import { useCallback, useEffect, useState } from "react";
import {
  applyPromptEvolution,
  distillPromptEvolution,
  getPromptEvolution,
  restorePromptEvolution,
  type EvolutionEvent,
  type EvolutionProposal,
} from "../lib/langgraph";

/** 提案 + 是否勾选 + 分发到别桶。text/applies_to 都可就地编辑。 */
export interface ProposalDraft extends EvolutionProposal {
  selected: boolean;
}

interface UseEvolution {
  /** 台账:已按 reviewType 过滤。 */
  events: EvolutionEvent[];
  /** 全部台账(未过滤)——用于「归纳建议」按 event_id 反查原始记录。 */
  allEvents: EvolutionEvent[];
  feedback: string;
  setFeedback: (v: string) => void;
  proposals: ProposalDraft[];
  toggleProposal: (index: number) => void;
  editProposalText: (index: number, text: string) => void;
  /** 切换某个提案对某个桶的分发勾选(applies_to 增删)。 */
  toggleProposalTarget: (index: number, bucket: string) => void;
  distilling: boolean;
  applying: boolean;
  /** 提炼:不传＝用顶部输入框新建一条;传台账记录＝就地提炼,把提案更新进该记录。 */
  distill: (sourceEvent?: EvolutionEvent) => Promise<void>;
  /** 批量提炼:把多条打回记录的意见合并成一条上下文,一次提炼出综合去重的提案。
   *  产物落到 batchSuggestion(不直接写入操作区),用户明确采纳后才 apply。 */
  distillBatch: (events: EvolutionEvent[]) => Promise<void>;
  /** 归纳建议:批量提炼产物,待用户「采纳并应用」。 */
  batchSuggestion: {
    event: EvolutionEvent;
    proposals: ProposalDraft[];
    summary: string;
  } | null;
  acceptBatchSuggestion: () => void;
  dismissBatchSuggestion: () => void;
  /** 载入某条已提炼记录的提案到操作区。 */
  loadEvent: (event: EvolutionEvent) => void;
  apply: () => Promise<void>;
  restore: (eventId: string) => Promise<void>;
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
  // 全部 events(未过滤)是权威数据;events 是按 reviewType 过滤后的视图。
  const [allEvents, setAllEvents] = useState<EvolutionEvent[]>([]);
  const [feedback, setFeedback] = useState("");
  const [proposals, setProposals] = useState<ProposalDraft[]>([]);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [distilling, setDistilling] = useState(false);
  const [applying, setApplying] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batchSuggestion, setBatchSuggestion] = useState<UseEvolution["batchSuggestion"]>(null);

  // 三桶隔离:「当前环节」抽屉只看当前 reviewType 的历史。跨环节全景由「预览总体」抽屉承担。
  const events = allEvents.filter((e) => e.review_type === reviewType);

  const refreshEvents = useCallback(async () => {
    if (!novelName) return;
    try {
      setAllEvents(await getPromptEvolution(novelName));
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }, [novelName]);

  // 打开时:加载台账 + 用最近一次打回意见预填来源框,重置上一轮的提案/提示/建议。
  useEffect(() => {
    if (!open || !novelName) return;
    setFeedback(prefillFeedback);
    setProposals([]);
    setActiveEventId(null);
    setStatus(null);
    setError(null);
    setBatchSuggestion(null);
    void refreshEvents();
  }, [open, novelName, prefillFeedback, refreshEvents]);

  // 切换 reviewType 时也重置操作区(避免在弧线抽屉里残留正文抽屉的提案)。
  useEffect(() => {
    if (!open) return;
    setProposals([]);
    setActiveEventId(null);
    setBatchSuggestion(null);
  }, [reviewType, open]);

  const distill = useCallback(
    async (sourceEvent?: EvolutionEvent) => {
      // 来源:台账某条打回记录(就地提炼,更新该记录)或顶部输入框(新建一条)。
      const fb = (sourceEvent?.source_feedback ?? feedback).trim();
      if (!fb) return;
      setDistilling(true);
      setError(null);
      setStatus(null);
      try {
        const { event, summary } = await distillPromptEvolution(novelName, genre, {
          feedback: fb,
          review_type: sourceEvent?.review_type ?? reviewType,
          event_id: sourceEvent?.id,
        });
        setActiveEventId(event.id);
        setProposals(event.proposals.map((p) => ({ ...p, selected: true })));
        setStatus(
          event.proposals.length
            ? `已提炼 ${event.proposals.length} 条整改${summary ? `:${summary}` : ""}`
            : "未提炼出可用整改(可换更具体的意见再试)"
        );
        await refreshEvents();
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setDistilling(false);
      }
    },
    [feedback, reviewType, novelName, genre, refreshEvents]
  );

  const distillBatch = useCallback(
    async (evts: EvolutionEvent[]) => {
      // 合并多条打回意见成一条上下文,一次提炼出综合去重的提案——落到「归纳建议」区,不直接写入操作区。
      const merged = evts
        .map((ent, i) => `${i + 1}. ${ent.source_feedback.trim()}`)
        .filter((s) => s.trim())
        .join("\n")
        .trim();
      if (!merged) return;
      setDistilling(true);
      setError(null);
      setStatus(null);
      try {
        const { event, summary } = await distillPromptEvolution(novelName, genre, {
          feedback: merged,
          review_type: evts[0]?.review_type ?? reviewType,
        });
        if (event.proposals.length) {
          setBatchSuggestion({
            event,
            proposals: event.proposals.map((p) => ({ ...p, selected: true })),
            summary,
          });
          setStatus(`已从 ${evts.length} 条记录批量归纳出 ${event.proposals.length} 条建议,请审阅后决定是否采纳`);
        } else {
          setStatus("未归纳出可用建议(可换更具体的意见再试)");
        }
        await refreshEvents();
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setDistilling(false);
      }
    },
    [reviewType, novelName, genre, refreshEvents]
  );

  // 采纳归纳建议:把 batchSuggestion 提升为主操作区的提案。
  const acceptBatchSuggestion = useCallback(() => {
    if (!batchSuggestion) return;
    setActiveEventId(batchSuggestion.event.id);
    setProposals(batchSuggestion.proposals);
    setBatchSuggestion(null);
    setStatus("已载入归纳建议,请勾选要写入的条目后应用");
  }, [batchSuggestion]);

  const dismissBatchSuggestion = useCallback(() => {
    setBatchSuggestion(null);
    setStatus("已忽略本次归纳建议");
  }, []);

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

  // 分发到某桶:applies_to 增删。传入的 bucket 必须是 evolved_directives_* 桶名之一。
  const toggleProposalTarget = useCallback((index: number, bucket: string) => {
    setProposals((prev) =>
      prev.map((p, i) => {
        if (i !== index) return p;
        const has = (p.applies_to ?? []).includes(bucket);
        return {
          ...p,
          applies_to: has
            ? p.applies_to.filter((b) => b !== bucket)
            : [...(p.applies_to ?? []), bucket],
        };
      })
    );
  }, []);

  const apply = useCallback(async () => {
    if (!activeEventId) return;
    const selected = proposals
      .filter((p) => p.selected && p.text.trim())
      .map((p) => ({
        field: p.field,
        text: p.text.trim(),
        op: p.op,
        // 分发目标:每条整改除了主 field,还可同时写入其他桶。
        also_apply_to: p.applies_to ?? [],
      }));
    if (!selected.length) {
      setError("请至少勾选一条整改");
      return;
    }
    setApplying(true);
    setError(null);
    try {
      await applyPromptEvolution(novelName, genre, activeEventId, selected);
      setStatus(`已写入 ${selected.length} 条整改,下一次生成即生效`);
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
    allEvents,
    feedback,
    setFeedback,
    proposals,
    toggleProposal,
    editProposalText,
    toggleProposalTarget,
    distilling,
    applying,
    distill,
    distillBatch,
    batchSuggestion,
    acceptBatchSuggestion,
    dismissBatchSuggestion,
    loadEvent,
    apply,
    restore,
    refresh: refreshEvents,
    status,
    error,
  };
}
