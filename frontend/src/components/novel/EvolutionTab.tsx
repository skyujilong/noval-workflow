// 「本书进化」页：把最近一次人工打回意见提炼成整改提案，勾选确认后写进本书提示词；
// 下方是进化事件台账，已应用的可一键还原。数据逻辑在 useEvolution。

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useEvolution } from "../../hooks/useEvolution";
import { useReconcile } from "../../hooks/useReconcile";
import type { EvolutionEvent } from "../../lib/langgraph";
import { EditableDirectiveCard } from "./EditableDirectiveCard";

const FIELD_LABEL: Record<string, string> = {
  evolved_directives: "历史整改要点",
  chapter_review_checklist: "审核清单",
  chapter_style_rules: "文体风格",
};

const STATUS_LABEL: Record<string, string> = {
  proposed: "待应用",
  applied: "已应用",
  reverted: "已还原",
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "手动提炼",
  reject: "打回",
  import: "库导入",
  reconcile: "整理消解",
};

interface Props {
  novelName: string;
  genre: string;
  reviewType: string;
  prefillFeedback: string;
  open: boolean;
}

export function EvolutionTab({ novelName, genre, reviewType, prefillFeedback, open }: Props) {
  const ev = useEvolution(novelName, genre, reviewType, prefillFeedback, open);
  const rc = useReconcile(novelName, genre, open, ev.refresh);

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-gray-700">手动补充意见（可选）</h3>
        <p className="text-[11px] text-gray-400">
          打回意见已自动记录在下方台账、可直接逐条提炼；此处用于手动补充一条额外意见再提炼。已预填最近一次打回意见。
        </p>
        <Textarea
          value={ev.feedback}
          onChange={(e) => ev.setFeedback(e.target.value)}
          rows={4}
          placeholder="例如：战斗描写太拖沓，请把每场战斗压到 300 字内，多用短句。"
          className="text-xs"
        />
        <Button onClick={() => void ev.distill()} disabled={ev.distilling || !ev.feedback.trim()}>
          {ev.distilling ? "提炼中…" : "提炼整改"}
        </Button>
      </section>

      {ev.status && (
        <div className="rounded bg-green-50 p-2 text-xs text-green-700">{ev.status}</div>
      )}
      {ev.error && <div className="rounded bg-red-50 p-2 text-xs text-red-600">{ev.error}</div>}

      {ev.proposals.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium text-gray-700">整改提案（勾选要写入的）</h3>
          {ev.proposals.map((p, i) => (
            <EditableDirectiveCard
              key={i}
              title={FIELD_LABEL[p.field] ?? p.field}
              badge={p.conflicts_with ? `⚠ 覆盖原规则：${p.conflicts_with}` : undefined}
              badgeWarn={!!p.conflicts_with}
              hint={p.rationale || undefined}
              text={p.text}
              selected={p.selected}
              disabled={ev.applying}
              onToggle={() => ev.toggleProposal(i)}
              onChange={(t) => ev.editProposalText(i, t)}
            />
          ))}
          <div className="flex items-center gap-3">
            <Button onClick={() => void ev.apply()} disabled={ev.applying}>
              {ev.applying ? "写入中…" : "应用到本书提示词"}
            </Button>
            <span className="text-[11px] text-gray-400">
              下一章生成即生效；若要作用于当前这一章，请到「历史」时间线从本章 prepare 处重跑。
            </span>
          </div>
        </section>
      )}

      <ReconcileSection rc={rc} />

      <EventLedger ev={ev} />
    </div>
  );
}

function ReconcileSection({ rc }: { rc: ReturnType<typeof useReconcile> }) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">整理消解</h3>
        <Button
          variant="outline"
          onClick={() => void rc.run()}
          disabled={rc.previewing || rc.applying}
        >
          {rc.previewing ? "整理中…" : "🧩 整理消解累积整改"}
        </Button>
      </div>
      <p className="text-[11px] text-gray-400">
        把历次沉淀、可能重复或互相矛盾的「历史整改要点」用 LLM 重写成一份去重、无矛盾的自洽清单
        （冲突以更新的为准）。预览确认后整段替换，旧版进台账可还原。
      </p>

      {rc.status && (
        <div className="rounded bg-green-50 p-2 text-xs text-green-700">{rc.status}</div>
      )}
      {rc.error && <div className="rounded bg-red-50 p-2 text-xs text-red-600">{rc.error}</div>}

      {rc.preview && (
        <div className="space-y-2 rounded border border-gray-200 p-3">
          {rc.preview.summary && (
            <p className="text-[11px] text-gray-500">{rc.preview.summary}</p>
          )}
          {rc.preview.resolved.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-amber-700">
              {rc.preview.resolved.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="mb-1 text-[11px] text-gray-400">整理前</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-[11px] text-gray-500">
                {rc.preview.before}
              </pre>
            </div>
            <div>
              <div className="mb-1 text-[11px] text-gray-400">整理后（可编辑）</div>
              <Textarea
                value={rc.edited}
                onChange={(e) => rc.setEdited(e.target.value)}
                rows={8}
                className="text-[11px]"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={() => void rc.apply()} disabled={rc.applying || !rc.edited.trim()}>
              {rc.applying ? "写入中…" : "应用整理结果"}
            </Button>
            <Button variant="ghost" onClick={rc.cancel} disabled={rc.applying}>
              取消
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

// 台账 + 多选批量提炼：待提炼的打回记录（proposed 且无提案）可勾选，一次综合去重提炼。
function EventLedger({ ev }: { ev: ReturnType<typeof useEvolution> }) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const pending = ev.events.filter((e) => e.status === "proposed" && e.proposals.length === 0);
  const busy = ev.distilling || ev.applying;
  const selected = pending.filter((e) => selectedIds.has(e.id));
  const allSelected = pending.length > 0 && selected.length === pending.length;

  const toggle = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () =>
    setSelectedIds(allSelected ? new Set() : new Set(pending.map((e) => e.id)));
  const runBatch = async () => {
    await ev.distillBatch(selected);
    setSelectedIds(new Set());
  };

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-gray-700">进化台账（打回记录 · 逐条 / 批量提炼）</h3>
      <p className="text-[11px] text-gray-400">
        每次在正文/弧线审核处打回，意见会自动落一条记录。点「提炼」逐条转成提案，或勾选多条「批量提炼」一次综合去重。
      </p>

      {pending.length >= 2 && (
        <div className="flex items-center gap-3 rounded bg-gray-50 px-2 py-1.5 text-xs">
          <label className="flex items-center gap-1.5 text-gray-500">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={busy} />
            全选待提炼（{pending.length}）
          </label>
          <Button
            onClick={() => void runBatch()}
            disabled={busy || selected.length < 1}
            className="ml-auto"
          >
            {ev.distilling ? "提炼中…" : `批量提炼（${selected.length}）`}
          </Button>
        </div>
      )}

      {ev.events.length === 0 ? (
        <p className="text-xs text-gray-400">暂无记录。打回一次即会出现在这里。</p>
      ) : (
        ev.events.map((e) => (
          <EventRow
            key={e.id}
            event={e}
            busy={busy}
            selectable={e.status === "proposed" && e.proposals.length === 0}
            selected={selectedIds.has(e.id)}
            onToggleSelect={() => toggle(e.id)}
            onDistill={() => void ev.distill(e)}
            onLoad={() => ev.loadEvent(e)}
            onRestore={() => void ev.restore(e.id)}
          />
        ))
      )}
    </section>
  );
}

interface EventRowProps {
  event: EvolutionEvent;
  busy: boolean;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onDistill: () => void;
  onLoad: () => void;
  onRestore: () => void;
}

function EventRow({
  event,
  busy,
  selectable,
  selected,
  onToggleSelect,
  onDistill,
  onLoad,
  onRestore,
}: EventRowProps) {
  const proposed = event.status === "proposed";
  const hasProposals = event.proposals.length > 0;
  return (
    <div className="rounded border border-gray-200 p-2.5 text-xs">
      <div className="mb-1 flex items-center gap-2 text-gray-500">
        {selectable && (
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggleSelect}
            disabled={busy}
            className="shrink-0"
          />
        )}
        <span>{new Date(event.created_at).toLocaleString()}</span>
        <span className="rounded bg-gray-100 px-1.5 py-0.5">
          {TRIGGER_LABEL[event.trigger] ?? event.trigger}
        </span>
        <span className="rounded bg-gray-100 px-1.5 py-0.5">
          {STATUS_LABEL[event.status] ?? event.status}
        </span>
        <div className="ml-auto flex items-center gap-3">
          {proposed && !hasProposals && (
            <button
              type="button"
              onClick={onDistill}
              disabled={busy}
              className="font-medium text-blue-600 hover:underline disabled:opacity-40"
            >
              提炼
            </button>
          )}
          {proposed && hasProposals && (
            <button
              type="button"
              onClick={onLoad}
              disabled={busy}
              className="font-medium text-blue-600 hover:underline disabled:opacity-40"
            >
              载入提案（{event.proposals.length}）去应用
            </button>
          )}
          {event.status === "applied" && (
            <button type="button" onClick={onRestore} className="text-gray-400 hover:text-blue-600">
              还原
            </button>
          )}
        </div>
      </div>
      {event.source_feedback && (
        <p className="line-clamp-3 text-gray-600">{event.source_feedback}</p>
      )}
      {Object.keys(event.applied).length > 0 && (
        <p className="mt-1 text-[11px] text-gray-400">
          已写入：{Object.keys(event.applied).map((f) => FIELD_LABEL[f] ?? f).join("、")}
        </p>
      )}
    </div>
  );
}
