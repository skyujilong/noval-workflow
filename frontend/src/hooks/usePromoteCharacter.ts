// 次要角色「提升为重要角色」的会话状态机（Part 2）。
//
// 一次提升会话：open(卡) → 选目标 role → 生成草稿(LLM) → 人工审改 → 落库。
// 逻辑全收在此 hook，PromoteCharacterPanel 只做声明式渲染。thread_id 与刷新回调由父层注入。

import { useCallback, useRef, useState } from "react";
import {
  promoteCharacterApply,
  promoteCharacterDraft,
  PROMOTABLE_ROLES,
  type CharacterPromotePatch,
} from "../lib/langgraph";
import type { EntityCard } from "../lib/types";

// choosing：选 role、未出草稿；drafting：调 LLM 中；editing：草稿就绪可审改；applying：落库中。
type PromotePhase = "choosing" | "drafting" | "editing" | "applying";

interface PromoteSession {
  card: EntityCard; // 被提升的次要角色卡（现状，只读参照）
  targetRole: string; // 目标重要角色定位
  phase: PromotePhase;
  draft: CharacterPromotePatch | null; // LLM 草稿，editing 阶段可逐字段改
  error: string | null;
}

export interface UsePromoteCharacter {
  session: PromoteSession | null; // null = 面板关闭
  busy: boolean; // drafting / applying 中（禁用交互）
  open: (card: EntityCard) => void;
  close: () => void;
  setTargetRole: (role: string) => void;
  generateDraft: () => void;
  setField: (key: keyof CharacterPromotePatch, value: string) => void;
  apply: () => void;
}

/**
 * @param threadId 当前小说 thread（带外写卡的目标）
 * @param onApplied 落库成功回调（父层应 refreshValues 刷新卡库）
 */
export function usePromoteCharacter(
  threadId: string,
  onApplied: () => void | Promise<void>
): UsePromoteCharacter {
  const [session, setSession] = useState<PromoteSession | null>(null);
  // 镜像最新 session，供事件处理器里的异步流程读取最新 targetRole/card/draft，
  // 避免在 setState updater 里塞副作用（StrictMode 会双调 updater 致请求发两次）。
  const sessionRef = useRef<PromoteSession | null>(null);
  sessionRef.current = session;
  const busy = session?.phase === "drafting" || session?.phase === "applying";

  const open = useCallback((card: EntityCard) => {
    setSession({ card, targetRole: PROMOTABLE_ROLES[0], phase: "choosing", draft: null, error: null });
  }, []);

  const close = useCallback(() => setSession(null), []);

  const setTargetRole = useCallback((role: string) => {
    // 改目标 role 会作废已生成草稿（草稿是按旧 role 生成的），回到 choosing 重新生成。
    setSession((s) => (s ? { ...s, targetRole: role, draft: null, phase: "choosing", error: null } : s));
  }, []);

  const generateDraft = useCallback(() => {
    const cur = sessionRef.current;
    if (!cur || cur.phase === "drafting") return; // 已在生成中则忽略重复点击
    setSession({ ...cur, phase: "drafting", error: null });
    void (async () => {
      try {
        const resp = await promoteCharacterDraft(threadId, cur.card.name, cur.targetRole);
        setSession((s) => (s ? { ...s, draft: resp.patch, phase: "editing" } : s));
      } catch (e) {
        setSession((s) =>
          s ? { ...s, phase: "choosing", error: e instanceof Error ? e.message : String(e) } : s
        );
      }
    })();
  }, [threadId]);

  const setField = useCallback((key: keyof CharacterPromotePatch, value: string) => {
    setSession((s) => (s && s.draft ? { ...s, draft: { ...s.draft, [key]: value } } : s));
  }, []);

  const apply = useCallback(() => {
    const cur = sessionRef.current;
    if (!cur || !cur.draft || cur.phase === "applying") return; // 无草稿或已在落库则忽略
    const draft = cur.draft;
    setSession({ ...cur, phase: "applying", error: null });
    void (async () => {
      try {
        await promoteCharacterApply(threadId, cur.card.name, draft);
        await onApplied();
        setSession(null); // 成功即关面板
      } catch (e) {
        setSession((s) =>
          s ? { ...s, phase: "editing", error: e instanceof Error ? e.message : String(e) } : s
        );
      }
    })();
  }, [threadId, onApplied]);

  return { session, busy, open, close, setTargetRole, generateDraft, setField, apply };
}
