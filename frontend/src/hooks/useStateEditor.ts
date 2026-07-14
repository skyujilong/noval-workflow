// 「就地编辑当前 state」的编辑态逻辑：文本字段草稿 + 伏笔台账结构化草稿的 dirty 追踪与
// 只提交改动字段的保存。保存后由 onSaved 让父层「只刷新 values、保留中断」。
// 表现层见 components/state/StateEditPanel.tsx。

import { useCallback, useEffect, useMemo, useState } from "react";
import { updateThreadState } from "../lib/langgraph";
import type { NovelState } from "../lib/types";
import {
  buildEntityCardsJson,
  buildTextDraft,
  diffTextKeys,
  entityCardsJsonEqual,
  ledgerDraftEqual,
  ledgerDraftValue,
  parseEntityCardsJson,
  toLedgerDraft,
  type EditableStateKey,
  type EditableStatePatch,
  type EditableTextKey,
  type LedgerDraft,
  type TextDraft,
} from "../lib/editableState";

interface Params {
  threadId: string;
  /** 当前 thread 快照（打开时据此初始化草稿；不随其变化而重置，避免清掉正在编辑的内容） */
  state: NovelState;
  /** 面板是否打开：由 false→true 时用最新 state 重置草稿与基线 */
  open: boolean;
  /**
   * 保存成功回调。父层应在此**只刷新 values**（useRun.refreshValues），
   * 切勿跑常规 refresh —— update_state 会清空中断源，常规 refresh 会让中断表单消失。
   */
  onSaved?: () => void | Promise<void>;
}

export interface UseStateEditor {
  textDraft: TextDraft;
  ledger: LedgerDraft;
  /** 实体卡 JSON 源码草稿 */
  entityCardsJson: string;
  /** 实体卡 JSON 校验错误（null = 合法）——非 null 时禁止保存 */
  entityCardsError: string | null;
  /** 与基线不同的字段集合（含 "foreshadowing" / "entity_cards"，供逐字段标记「已改」） */
  dirtyKeys: Set<EditableStateKey>;
  dirtyCount: number;
  saving: boolean;
  saveError: string | null;
  /** 最近一次保存成功（任一字段编辑后复位）——用于展示「已保存」 */
  justSaved: boolean;
  setTextField: (key: EditableTextKey, value: string) => void;
  setLedger: (draft: LedgerDraft) => void;
  setEntityCardsJson: (value: string) => void;
  resetField: (key: EditableStateKey) => void;
  resetAll: () => void;
  save: () => Promise<void>;
}

export function useStateEditor({ threadId, state, open, onSaved }: Params): UseStateEditor {
  const [textDraft, setTextDraft] = useState<TextDraft>(() => buildTextDraft(state));
  const [textBaseline, setTextBaseline] = useState<TextDraft>(() => buildTextDraft(state));
  const [ledger, setLedgerState] = useState<LedgerDraft>(() => toLedgerDraft(state.foreshadowing));
  const [ledgerBaseline, setLedgerBaseline] = useState<LedgerDraft>(() =>
    toLedgerDraft(state.foreshadowing)
  );
  const [entityCardsJson, setEntityCardsJsonState] = useState<string>(() =>
    buildEntityCardsJson(state)
  );
  const [entityCardsBaseline, setEntityCardsBaseline] = useState<string>(() =>
    buildEntityCardsJson(state)
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  // 打开时用最新 state 重置草稿+基线；关闭态不跟随 state 变化，避免打字被外部刷新清空。
  useEffect(() => {
    if (!open) return;
    const text = buildTextDraft(state);
    const led = toLedgerDraft(state.foreshadowing);
    const cardsJson = buildEntityCardsJson(state);
    setTextDraft(text);
    setTextBaseline(text);
    setLedgerState(led);
    setLedgerBaseline(led);
    setEntityCardsJsonState(cardsJson);
    setEntityCardsBaseline(cardsJson);
    setSaveError(null);
    setJustSaved(false);
    // 仅在「打开」或「切换 thread」时重置；刻意不依赖 state。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, threadId]);

  const { dirtyKeys, dirtyCount } = useMemo(() => {
    const keys = new Set<EditableStateKey>(diffTextKeys(textDraft, textBaseline));
    if (!ledgerDraftEqual(ledger, ledgerBaseline)) keys.add("foreshadowing");
    if (!entityCardsJsonEqual(entityCardsJson, entityCardsBaseline)) keys.add("entity_cards");
    return { dirtyKeys: keys, dirtyCount: keys.size };
  }, [textDraft, textBaseline, ledger, ledgerBaseline, entityCardsJson, entityCardsBaseline]);

  // 实体卡 JSON 校验错误——仅在「已改」时校验（未改动的基线值默认合法，不打扰）。
  const entityCardsError = useMemo(() => {
    if (!dirtyKeys.has("entity_cards")) return null;
    return parseEntityCardsJson(entityCardsJson).error ?? null;
  }, [dirtyKeys, entityCardsJson]);

  const setTextField = useCallback((key: EditableTextKey, value: string) => {
    setTextDraft((prev) => ({ ...prev, [key]: value }));
    setJustSaved(false);
  }, []);

  const setLedger = useCallback((draft: LedgerDraft) => {
    setLedgerState(draft);
    setJustSaved(false);
  }, []);

  const setEntityCardsJson = useCallback((value: string) => {
    setEntityCardsJsonState(value);
    setJustSaved(false);
  }, []);

  const resetField = useCallback(
    (key: EditableStateKey) => {
      if (key === "foreshadowing") {
        setLedgerState(ledgerBaseline);
      } else if (key === "entity_cards") {
        setEntityCardsJsonState(entityCardsBaseline);
      } else {
        setTextDraft((prev) => ({ ...prev, [key]: textBaseline[key as EditableTextKey] }));
      }
    },
    [textBaseline, ledgerBaseline, entityCardsBaseline]
  );

  const resetAll = useCallback(() => {
    setTextDraft(textBaseline);
    setLedgerState(ledgerBaseline);
    setEntityCardsJsonState(entityCardsBaseline);
  }, [textBaseline, ledgerBaseline, entityCardsBaseline]);

  const save = useCallback(async () => {
    // 用宽松类型累积，边界处断言回 patch 类型（规避联合 key 写入的 TS 限制）
    const patch: Record<string, unknown> = {};
    for (const key of diffTextKeys(textDraft, textBaseline)) patch[key] = textDraft[key];
    const ledgerDirty = !ledgerDraftEqual(ledger, ledgerBaseline);
    if (ledgerDirty) patch.foreshadowing = ledgerDraftValue(ledger);
    const cardsDirty = !entityCardsJsonEqual(entityCardsJson, entityCardsBaseline);
    if (cardsDirty) {
      // 非法 JSON 直接中止整次保存（不部分提交），把错误暴露到 saveError 引导修复。
      const parsed = parseEntityCardsJson(entityCardsJson);
      if (!parsed.ok) {
        setSaveError(`登场实体卡未保存：${parsed.error}`);
        return;
      }
      patch.entity_cards = parsed.value;
    }
    if (Object.keys(patch).length === 0) return;

    setSaving(true);
    setSaveError(null);
    try {
      await updateThreadState(threadId, patch as EditableStatePatch);
      setTextBaseline(textDraft); // 基线推进到已保存态，dirty 归零
      setLedgerBaseline(ledger);
      setEntityCardsBaseline(entityCardsJson);
      setJustSaved(true);
      await onSaved?.(); // 父层只刷新 values，不动 interrupt
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [
    textDraft,
    textBaseline,
    ledger,
    ledgerBaseline,
    entityCardsJson,
    entityCardsBaseline,
    threadId,
    onSaved,
  ]);

  return {
    textDraft,
    ledger,
    entityCardsJson,
    entityCardsError,
    dirtyKeys,
    dirtyCount,
    saving,
    saveError,
    justSaved,
    setTextField,
    setLedger,
    setEntityCardsJson,
    resetField,
    resetAll,
    save,
  };
}
