// 就地编辑当前节点 state 的抽屉：暂停点手动纠正快照台账 / 基础设定 / 当前草稿，
// 保存即 LangGraph update_state（只 patch 改动字段），改完照常「通过/提交」继续。
//
// 关键约束（见 plan：state-binary-elephant.md）：
//   - 只在未运行时可保存（disabled=running/busy）——LangGraph 不允许节点执行途中改 state。
//   - 保存后父层只刷新 values（onSaved=useRun.refreshValues），不动 interrupt，中断表单不消失。
//   - foreshadowing 为结构化 dict，用结构化编辑器（ForeshadowingEditor）而非手写 JSON。
//   - reducer/进度字段不在白名单（无法经此误改）。

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useStateEditor } from "../../hooks/useStateEditor";
import {
  EDITABLE_FIELDS,
  EDITABLE_GROUP_LABELS,
  EDITABLE_GROUP_ORDER,
  type EditableFieldDef,
  type EditableStateKey,
  type EditableTextKey,
  type LedgerDraft,
} from "../../lib/editableState";
import type { NovelState } from "../../lib/types";
import { ForeshadowingEditor } from "./ForeshadowingEditor";

interface Props {
  open: boolean;
  threadId: string;
  state: NovelState;
  /** run 进行中 / 后台忙：禁止保存（LangGraph 不允许节点执行途中改 state） */
  disabled: boolean;
  onClose: () => void;
  /** 保存成功回调：父层只刷新 values（useRun.refreshValues） */
  onSaved: () => void | Promise<void>;
}

/** 字段头：标签 + 已改标记 + 撤销 */
function FieldHead({
  label,
  dirty,
  onReset,
}: {
  label: string;
  dirty: boolean;
  onReset: () => void;
}) {
  return (
    <div className="mb-1 flex items-center justify-between">
      <Label className="text-gray-700">
        {label}
        {dirty && (
          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-normal text-amber-700">
            已改
          </span>
        )}
      </Label>
      <button
        type="button"
        onClick={onReset}
        disabled={!dirty}
        className="text-xs text-gray-400 hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-40"
      >
        撤销
      </button>
    </div>
  );
}

interface TextFieldProps {
  field: EditableFieldDef;
  value: string;
  dirty: boolean;
  onChange: (key: EditableTextKey, value: string) => void;
  onReset: () => void;
}

function TextField({ field, value, dirty, onChange, onReset }: TextFieldProps) {
  const rows = field.key === "current_draft" ? 12 : 6;
  return (
    <div>
      <FieldHead label={field.label} dirty={dirty} onReset={onReset} />
      <Textarea
        value={value}
        onChange={(e) => onChange(field.key as EditableTextKey, e.target.value)}
        rows={rows}
        className="font-mono text-xs"
      />
    </div>
  );
}

interface LedgerFieldProps {
  field: EditableFieldDef;
  ledger: LedgerDraft;
  dirty: boolean;
  disabled: boolean;
  onChange: (draft: LedgerDraft) => void;
  onReset: () => void;
}

function LedgerField({ field, ledger, dirty, disabled, onChange, onReset }: LedgerFieldProps) {
  return (
    <div>
      <FieldHead label={field.label} dirty={dirty} onReset={onReset} />
      {ledger.mode === "structured" ? (
        <ForeshadowingEditor
          value={ledger.value}
          disabled={disabled}
          onChange={(value) => onChange({ mode: "structured", value })}
        />
      ) : (
        <div>
          <div className="mb-1 text-xs text-amber-600">
            检测到旧版文本格式，按原文编辑（下次生成会自动迁移为结构化）。
          </div>
          <Textarea
            value={ledger.text}
            disabled={disabled}
            onChange={(e) => onChange({ mode: "legacy", text: e.target.value })}
            rows={8}
            className="font-mono text-xs"
          />
        </div>
      )}
    </div>
  );
}

export function StateEditPanel({ open, threadId, state, disabled, onClose, onSaved }: Props) {
  const {
    textDraft,
    ledger,
    dirtyKeys,
    dirtyCount,
    saving,
    saveError,
    justSaved,
    setTextField,
    setLedger,
    resetField,
    resetAll,
    save,
  } = useStateEditor({ threadId, state, open, onSaved });

  const canSave = !disabled && !saving && dirtyCount > 0;

  const renderField = (f: EditableFieldDef) => {
    const dirty = dirtyKeys.has(f.key as EditableStateKey);
    if (f.kind === "ledger") {
      return (
        <LedgerField
          key={f.key}
          field={f}
          ledger={ledger}
          dirty={dirty}
          disabled={disabled}
          onChange={setLedger}
          onReset={() => resetField(f.key)}
        />
      );
    }
    return (
      <TextField
        key={f.key}
        field={f}
        value={textDraft[f.key as EditableTextKey]}
        dirty={dirty}
        onChange={setTextField}
        onReset={() => resetField(f.key)}
      />
    );
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0">
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>编辑当前状态 · {state.novel_name || "未命名"}</SheetTitle>
          <SheetDescription>
            就地修改当前节点的 state（快照台账 / 基础设定 / 当前草稿），保存后照常「通过 / 提交意见」继续。
            只提交改动过的字段。仅在未运行时可保存。
          </SheetDescription>
        </SheetHeader>

        {disabled && (
          <div className="mx-6 mt-4 flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
            该小说正在运行 / 后台处理中，暂不可保存（不能在节点执行途中改 state）。可先查看，待暂停后再改。
          </div>
        )}
        {saveError && (
          <div className="mx-6 mt-4 rounded bg-red-50 p-2 text-xs text-red-600">{saveError}</div>
        )}

        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-4">
          {EDITABLE_GROUP_ORDER.map((group) => (
            <section key={group} className="space-y-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                {EDITABLE_GROUP_LABELS[group]}
              </h4>
              {EDITABLE_FIELDS.filter((f) => f.group === group).map(renderField)}
            </section>
          ))}
        </div>

        <SheetFooter className="items-center gap-2 border-t px-6 py-4 sm:gap-2">
          <div className="mr-auto text-xs text-gray-400">
            {justSaved && dirtyCount === 0
              ? "已保存"
              : dirtyCount > 0
                ? `${dirtyCount} 个字段待保存`
                : "无改动"}
          </div>
          <Button variant="ghost" onClick={resetAll} disabled={dirtyCount === 0 || saving}>
            全部撤销
          </Button>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            关闭
          </Button>
          <Button onClick={() => void save()} disabled={!canSave}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
