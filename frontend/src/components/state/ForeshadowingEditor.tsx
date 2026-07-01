// 伏笔台账结构化编辑器：把 foreshadowing dict（{pending:[], collected:[]}）拆成两组卡片，
// 逐字段填写，支持增删与「悬置 ⇄ 已收」互转——无需手写 JSON。
// 结构见 src/novel_workflow/prompts/ledger.py。

import { Textarea } from "@/components/ui/textarea";
import {
  FREEDOM_OPTIONS,
  newForeshadowingEntry,
  type ForeshadowingEntry,
  type ForeshadowingLedgerObj,
} from "../../lib/editableState";

const inputCls =
  "w-full rounded-md border border-input bg-background px-2 py-1 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:opacity-50";

type Bucket = "pending" | "collected";

interface Props {
  value: ForeshadowingLedgerObj;
  onChange: (value: ForeshadowingLedgerObj) => void;
  disabled?: boolean;
}

interface EntryCardProps {
  entry: ForeshadowingEntry;
  bucket: Bucket;
  disabled?: boolean;
  onPatch: (patch: Partial<ForeshadowingEntry>) => void;
  onRemove: () => void;
  onMove: () => void;
}

function LabeledText({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="mb-0.5 text-[11px] text-gray-400">{label}</div>
      <Textarea
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        className="min-h-0 text-xs"
      />
    </div>
  );
}

function EntryCard({ entry, bucket, disabled, onPatch, onRemove, onMove }: EntryCardProps) {
  return (
    <div className="space-y-2 rounded-md border border-gray-200 bg-gray-50/60 p-2">
      <div className="flex items-center gap-2">
        <input
          className={inputCls + " w-16 font-mono"}
          placeholder="F01"
          value={entry.id}
          disabled={disabled}
          onChange={(e) => onPatch({ id: e.target.value })}
        />
        <input
          className={inputCls + " flex-1"}
          placeholder="伏笔名称"
          value={entry.name}
          disabled={disabled}
          onChange={(e) => onPatch({ name: e.target.value })}
        />
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          title="删除该伏笔"
          className="rounded px-1.5 text-gray-400 hover:text-red-500 disabled:opacity-40"
        >
          ✕
        </button>
      </div>

      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1 text-[11px] text-gray-400">
          批次
          <input
            type="number"
            className={inputCls + " w-14"}
            value={entry.planted_batch}
            disabled={disabled}
            onChange={(e) => onPatch({ planted_batch: Number(e.target.value) || 0 })}
          />
        </label>
        <label className="flex items-center gap-1 text-[11px] text-gray-400">
          自由度
          <select
            className={inputCls + " w-16"}
            value={entry.freedom}
            disabled={disabled}
            onChange={(e) => onPatch({ freedom: e.target.value })}
          >
            {FREEDOM_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        {bucket === "collected" && (
          <label className="flex items-center gap-1 text-[11px] text-gray-400">
            回收章节
            <input
              type="number"
              className={inputCls + " w-16"}
              value={entry.recovered_at_chapter ?? 0}
              disabled={disabled}
              onChange={(e) => onPatch({ recovered_at_chapter: Number(e.target.value) || 0 })}
            />
          </label>
        )}
        <button
          type="button"
          onClick={onMove}
          disabled={disabled}
          className="ml-auto rounded border border-gray-200 px-2 py-0.5 text-[11px] text-gray-500 hover:border-blue-300 hover:text-blue-600 disabled:opacity-40"
        >
          {bucket === "pending" ? "标记已收 →" : "← 移回悬置"}
        </button>
      </div>

      <LabeledText
        label="当前潜伏表现"
        value={entry.current_appearance}
        disabled={disabled}
        onChange={(v) => onPatch({ current_appearance: v })}
      />
      <LabeledText
        label="核心作用"
        value={entry.core_purpose}
        disabled={disabled}
        onChange={(v) => onPatch({ core_purpose: v })}
      />
      <LabeledText
        label="预定回收区间"
        value={entry.planned_recovery_range}
        disabled={disabled}
        onChange={(v) => onPatch({ planned_recovery_range: v })}
      />
    </div>
  );
}

export function ForeshadowingEditor({ value, onChange, disabled }: Props) {
  const patchEntry = (bucket: Bucket, idx: number, patch: Partial<ForeshadowingEntry>) => {
    onChange({
      ...value,
      [bucket]: value[bucket].map((e, i) => (i === idx ? { ...e, ...patch } : e)),
    });
  };

  const removeEntry = (bucket: Bucket, idx: number) => {
    onChange({ ...value, [bucket]: value[bucket].filter((_, i) => i !== idx) });
  };

  const addPending = () => {
    onChange({ ...value, pending: [...value.pending, newForeshadowingEntry()] });
  };

  const markCollected = (idx: number) => {
    const entry: ForeshadowingEntry = {
      ...value.pending[idx],
      recovered_at_chapter: value.pending[idx].recovered_at_chapter ?? 0,
    };
    onChange({
      pending: value.pending.filter((_, i) => i !== idx),
      collected: [...value.collected, entry],
    });
  };

  const markPending = (idx: number) => {
    const entry = { ...value.collected[idx] };
    delete entry.recovered_at_chapter;
    onChange({
      collected: value.collected.filter((_, i) => i !== idx),
      pending: [...value.pending, entry],
    });
  };

  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-medium text-gray-600">悬置（{value.pending.length}）</span>
          <button
            type="button"
            onClick={addPending}
            disabled={disabled}
            className="rounded border border-gray-200 px-2 py-0.5 text-[11px] text-gray-500 hover:border-blue-300 hover:text-blue-600 disabled:opacity-40"
          >
            + 新增伏笔
          </button>
        </div>
        {value.pending.length === 0 ? (
          <div className="rounded border border-dashed border-gray-200 py-3 text-center text-[11px] text-gray-400">
            暂无悬置伏笔
          </div>
        ) : (
          <div className="space-y-2">
            {value.pending.map((entry, i) => (
              <EntryCard
                key={i}
                entry={entry}
                bucket="pending"
                disabled={disabled}
                onPatch={(p) => patchEntry("pending", i, p)}
                onRemove={() => removeEntry("pending", i)}
                onMove={() => markCollected(i)}
              />
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="mb-1 text-xs font-medium text-gray-600">已收（{value.collected.length}）</div>
        {value.collected.length === 0 ? (
          <div className="rounded border border-dashed border-gray-200 py-3 text-center text-[11px] text-gray-400">
            暂无已收伏笔
          </div>
        ) : (
          <div className="space-y-2">
            {value.collected.map((entry, i) => (
              <EntryCard
                key={i}
                entry={entry}
                bucket="collected"
                disabled={disabled}
                onPatch={(p) => patchEntry("collected", i, p)}
                onRemove={() => removeEntry("collected", i)}
                onMove={() => markPending(i)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
