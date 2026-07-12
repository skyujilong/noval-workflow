// 本书进化(三桶隔离版):打开时的 reviewType 决定「当前环节」,所有内容按环节隔离。
// 顶部展示当前环节【已生效整改要点】(evolved_directives_<type> 全文列表);
// 中部提供提炼/整改/分发(每条整改可勾选分发到其他环节);
// 下部台账仅显示当前环节,状态灯一眼看出「已生效/待提炼/已提炼未应用」;
// 底部「归纳建议」承接批量提炼产物,采纳前不写入。
// 「预览总体」按钮打开 AllEvolvedPreviewModal 抽屉,并排看三桶全景。

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useEvolution, type ProposalDraft } from "../../hooks/useEvolution";
import { useReconcile } from "../../hooks/useReconcile";
import { getAllEvolvedDirectives, type EvolutionEvent } from "../../lib/langgraph";
import { reviewTypeLabel } from "../../lib/types";
import { EditableDirectiveCard } from "./EditableDirectiveCard";
import { AllEvolvedPreviewModal } from "./AllEvolvedPreviewModal";

const FIELD_LABEL: Record<string, string> = {
  evolved_directives_chapter: "历史整改要点(章节正文)",
  evolved_directives_arc_outline: "历史整改要点(弧线大纲)",
  evolved_directives_scene_beats: "历史整改要点(Scene beats)",
  chapter_review_checklist: "审核清单",
  chapter_style_rules: "文体风格",
  // 老字段仅用于兼容遗留台账事件的展示,新提炼产物不会再使用它。
  evolved_directives: "历史整改要点(旧格式)",
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "手动提炼",
  reject: "打回",
  import: "库导入",
  reconcile: "整理消解",
};

// 当前环节 → 可分发的「其他桶」列表(仅 evolved_directives_* 三桶互相分发)。
const ALL_BUCKETS = ["chapter", "arc_outline", "scene_beats"] as const;
type Bucket = (typeof ALL_BUCKETS)[number];
const BUCKET_TO_FIELD: Record<Bucket, string> = {
  chapter: "evolved_directives_chapter",
  arc_outline: "evolved_directives_arc_outline",
  scene_beats: "evolved_directives_scene_beats",
};
const FIELD_TO_BUCKET: Record<string, Bucket> = {
  evolved_directives_chapter: "chapter",
  evolved_directives_arc_outline: "arc_outline",
  evolved_directives_scene_beats: "scene_beats",
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
  const rc = useReconcile(novelName, genre, reviewType, open, ev.refresh);
  const [showAll, setShowAll] = useState(false);

  const currentBucket = FIELD_TO_BUCKET[reviewType]
    ? reviewType
    : reviewType in BUCKET_TO_FIELD
      ? reviewType
      : "chapter";

  return (
    <div className="space-y-5">
      {/* 顶部:当前环节标识 + 预览总体入口 */}
      <div className="flex items-center justify-between border-b pb-2">
        <div className="text-sm">
          <span className="text-gray-500">当前环节:</span>{" "}
          <span className="font-medium text-blue-600">{reviewTypeLabel(reviewType)}</span>
          <span className="ml-2 text-[11px] text-gray-400">
            所有操作只作用于本环节,分发到其他环节需在提案上显式勾选
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowAll(true)}>
          预览总体 ⤢
        </Button>
      </div>

      {ev.status && (
        <div className="rounded bg-green-50 p-2 text-xs text-green-700">{ev.status}</div>
      )}
      {ev.error && <div className="rounded bg-red-50 p-2 text-xs text-red-600">{ev.error}</div>}

      {/* § 已生效整改要点(本环节当前桶的全文列表) */}
      <ActiveDirectives novelName={novelName} genre={genre} reviewType={reviewType} />

      {/* § 手动补充意见 */}
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-gray-700">手动补充意见(可选)</h3>
        <p className="text-[11px] text-gray-400">
          打回意见已自动记录在下方台账、可直接逐条提炼;此处用于手动补充一条额外意见再提炼。
        </p>
        <Textarea
          value={ev.feedback}
          onChange={(e) => ev.setFeedback(e.target.value)}
          rows={4}
          placeholder="例如:战斗描写太拖沓,请把每场战斗压到 300 字内,多用短句。"
          className="text-xs"
        />
        <Button onClick={() => void ev.distill()} disabled={ev.distilling || !ev.feedback.trim()}>
          {ev.distilling ? "提炼中…" : "提炼整改"}
        </Button>
      </section>

      {/* § 整改提案(带分发勾选) */}
      {ev.proposals.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-medium text-gray-700">整改提案(勾选要写入的)</h3>
          {ev.proposals.map((p, i) => (
            <ProposalCard
              key={i}
              proposal={p}
              index={i}
              currentBucket={currentBucket as Bucket}
              disabled={ev.applying}
              onToggle={() => ev.toggleProposal(i)}
              onChange={(t) => ev.editProposalText(i, t)}
              onToggleTarget={(bucket) => ev.toggleProposalTarget(i, bucket)}
            />
          ))}
          <div className="flex items-center gap-3">
            <Button onClick={() => void ev.apply()} disabled={ev.applying}>
              {ev.applying ? "写入中…" : "应用到本书提示词"}
            </Button>
            <span className="text-[11px] text-gray-400">
              下一次生成即生效;分发到其他环节需在上方各提案下方显式勾选。
            </span>
          </div>
        </section>
      )}

      {/* § 整理消解(仅当前环节) */}
      <ReconcileSection rc={rc} reviewType={reviewType} />

      {/* § 台账(仅当前环节)+ 批量提炼→归纳建议 */}
      <EventLedger ev={ev} reviewType={reviewType} />

      {/* § 归纳建议(批量提炼产物,采纳前不写入) */}
      {ev.batchSuggestion && (
        <BatchSuggestionSection ev={ev} currentBucket={currentBucket as Bucket} />
      )}

      <AllEvolvedPreviewModal
        open={showAll}
        novelName={novelName}
        genre={genre}
        onClose={() => setShowAll(false)}
      />
    </div>
  );
}

// § 已生效整改要点——独立组件,单独拉当前环节 evolved_directives 全文展示。
// 数据源用 getAllEvolvedDirectives 会一次拉三桶,当前只展示自己那桶,余下两桶属于预览抽屉的关切。
function ActiveDirectives({
  novelName,
  genre,
  reviewType,
}: {
  novelName: string;
  genre: string;
  reviewType: string;
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!novelName) return;
    setLoading(true);
    try {
      const data = await getAllEvolvedDirectives(novelName, genre);
      const bucketText =
        reviewType === "chapter"
          ? data.chapter
          : reviewType === "arc_outline"
            ? data.arc_outline
            : reviewType === "scene_beats"
              ? data.scene_beats
              : "";
      setText(bucketText);
    } finally {
      setLoading(false);
    }
  };

  // 挂载 + reviewType/novel/genre 变化时拉取。写入路径(apply/reconcile)完成后不主动刷新——
  // 用户可点右上「🔄 刷新」按钮同步(避免与 useEvolution 的 refresh 竞态)。
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelName, genre, reviewType]);

  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">
          已生效的整改要点(作用于 {reviewTypeLabel(reviewType)})
        </h3>
        <Button variant="ghost" size="sm" onClick={() => void load()} disabled={loading}>
          {loading ? "刷新中…" : "🔄 刷新"}
        </Button>
      </div>
      <div className="rounded border border-gray-200 bg-white p-2">
        {lines.length === 0 ? (
          <p className="text-xs text-gray-400">(暂无沉淀。手动提炼或从打回台账提炼后,应用即会出现在此处)</p>
        ) : (
          <ul className="space-y-1 text-xs text-gray-700">
            {lines.map((line, i) => (
              <li key={i} className="rounded bg-gray-50 px-2 py-1">
                {line}
              </li>
            ))}
          </ul>
        )}
        {lines.length > 0 && (
          <p className="mt-2 text-[11px] text-gray-400">共 {lines.length} 条 · 下一次生成会被注入到提示词末尾(最高优先级)</p>
        )}
      </div>
    </section>
  );
}

function ProposalCard({
  proposal,
  currentBucket,
  disabled,
  onToggle,
  onChange,
  onToggleTarget,
}: {
  proposal: ProposalDraft;
  index: number;
  currentBucket: Bucket;
  disabled: boolean;
  onToggle: () => void;
  onChange: (t: string) => void;
  onToggleTarget: (bucket: string) => void;
}) {
  const title = FIELD_LABEL[proposal.field] ?? proposal.field;
  const badge = proposal.conflicts_with ? `⚠ 覆盖原规则:${proposal.conflicts_with}` : undefined;
  const otherBuckets = ALL_BUCKETS.filter((b) => b !== currentBucket);
  return (
    <div className="space-y-2">
      <EditableDirectiveCard
        title={title}
        badge={badge}
        badgeWarn={!!proposal.conflicts_with}
        hint={proposal.rationale || undefined}
        text={proposal.text}
        selected={proposal.selected}
        disabled={disabled}
        onToggle={onToggle}
        onChange={onChange}
      />
      {/* 分发勾选:严格默认(仅当前环节),用户勾选后同步写入其他桶。 */}
      <div className="ml-6 flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span>↳ 也应用到:</span>
        {otherBuckets.map((b) => {
          const field = BUCKET_TO_FIELD[b];
          const checked = (proposal.applies_to ?? []).includes(field);
          return (
            <label key={b} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggleTarget(field)}
                disabled={disabled}
              />
              {reviewTypeLabel(b)}
            </label>
          );
        })}
      </div>
    </div>
  );
}

function ReconcileSection({
  rc,
  reviewType,
}: {
  rc: ReturnType<typeof useReconcile>;
  reviewType: string;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">整理消解(当前环节)</h3>
        <Button
          variant="outline"
          onClick={() => void rc.run()}
          disabled={rc.previewing || rc.applying}
        >
          {rc.previewing ? "整理中…" : "🧩 整理消解本环节整改"}
        </Button>
      </div>
      <p className="text-[11px] text-gray-400">
        把「{reviewTypeLabel(reviewType)}」桶里可能重复或矛盾的整改用 LLM 重写成一份去重、无矛盾的自洽清单
        (冲突以更新的为准)。预览确认后整段替换,旧版进台账可还原。
      </p>

      {rc.status && <div className="rounded bg-green-50 p-2 text-xs text-green-700">{rc.status}</div>}
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
              <div className="mb-1 text-[11px] text-gray-400">整理后(可编辑)</div>
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

// 台账 + 多选批量提炼(产物落到「归纳建议」,不直接进操作区)。
function EventLedger({
  ev,
  reviewType,
}: {
  ev: ReturnType<typeof useEvolution>;
  reviewType: string;
}) {
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
      <h3 className="text-sm font-medium text-gray-700">
        进化台账(仅 {reviewTypeLabel(reviewType)} · 逐条 / 批量归纳)
      </h3>
      <p className="text-[11px] text-gray-400">
        每次在本环节审核处打回,意见会自动落一条记录。点「提炼」逐条转成提案,或勾选多条「批量归纳」得到一条综合去重的建议(需审阅后才写入)。
      </p>

      {pending.length >= 2 && (
        <div className="flex items-center gap-3 rounded bg-gray-50 px-2 py-1.5 text-xs">
          <label className="flex items-center gap-1.5 text-gray-500">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={busy} />
            全选待提炼({pending.length})
          </label>
          <Button
            onClick={() => void runBatch()}
            disabled={busy || selected.length < 1}
            className="ml-auto"
          >
            {ev.distilling ? "归纳中…" : `批量归纳({${selected.length}})`}
          </Button>
        </div>
      )}

      {ev.events.length === 0 ? (
        <p className="text-xs text-gray-400">暂无记录。在本环节打回一次即会出现在这里。</p>
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

// 状态灯:一眼分辨 已应用 / 已提炼未应用 / 待提炼 / 已还原。
function statusBadge(event: EvolutionEvent): { emoji: string; label: string; color: string } {
  if (event.status === "applied") return { emoji: "✅", label: "已生效", color: "bg-green-50 text-green-700" };
  if (event.status === "reverted") return { emoji: "⤴", label: "已还原", color: "bg-gray-100 text-gray-500" };
  if (event.status === "proposed" && event.proposals.length > 0)
    return { emoji: "📝", label: "已提炼未应用", color: "bg-blue-50 text-blue-700" };
  return { emoji: "⏳", label: "待提炼", color: "bg-amber-50 text-amber-700" };
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
  const reverted = event.status === "reverted";
  const hasProposals = event.proposals.length > 0;
  // 已还原的记录:提案还在,应该能重新载入应用(还原只回滚了 overrides,不销毁提炼产物)。
  // 已生效的记录:提案已作用,不再需要「载入应用」入口,仅保留「还原」。
  const canLoadProposals = hasProposals && (proposed || reverted);
  const s = statusBadge(event);
  const chapterHint =
    event.chapter_index !== null && event.chapter_index !== undefined
      ? ` · 第 ${event.chapter_index} 章`
      : "";
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
        <span className={`rounded px-1.5 py-0.5 ${s.color}`}>
          {s.emoji} {s.label}
        </span>
        <span>{new Date(event.created_at).toLocaleString()}</span>
        <span className="rounded bg-gray-100 px-1.5 py-0.5">
          {TRIGGER_LABEL[event.trigger] ?? event.trigger}
        </span>
        <span className="text-gray-400">{chapterHint}</span>
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
          {canLoadProposals && (
            <button
              type="button"
              onClick={onLoad}
              disabled={busy}
              className="font-medium text-blue-600 hover:underline disabled:opacity-40"
            >
              {reverted
                ? `重新载入提案(${event.proposals.length})`
                : `载入提案(${event.proposals.length})去应用`}
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
          已写入:{Object.keys(event.applied).map((f) => FIELD_LABEL[f] ?? f).join("、")}
        </p>
      )}
      {/* 已提炼未应用:直接展示提案摘要,不再需要「载入操作区」这一步 */}
      {hasProposals && (
        <div className="mt-2 space-y-0.5">
          {event.proposals.slice(0, 3).map((p, i) => (
            <div key={i} className="rounded bg-blue-50 px-2 py-1 text-[11px] text-blue-900">
              {FIELD_LABEL[p.field] ?? p.field}:{p.text.slice(0, 80)}
              {p.text.length > 80 ? "…" : ""}
            </div>
          ))}
          {event.proposals.length > 3 && (
            <div className="text-[11px] text-gray-400">…共 {event.proposals.length} 条</div>
          )}
        </div>
      )}
    </div>
  );
}

// § 归纳建议——批量提炼产物的暂存区。用户明确「采纳并应用」才把它提到主提案区落地。
function BatchSuggestionSection({
  ev,
  currentBucket,
}: {
  ev: ReturnType<typeof useEvolution>;
  currentBucket: Bucket;
}) {
  const s = ev.batchSuggestion;
  if (!s) return null;
  return (
    <section className="space-y-2 rounded border border-purple-300 bg-purple-50 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-purple-800">📌 归纳建议(批量提炼 · 待采纳)</h3>
        <div className="flex gap-2">
          <Button size="sm" onClick={ev.acceptBatchSuggestion}>
            ✓ 采纳并应用
          </Button>
          <Button size="sm" variant="ghost" onClick={ev.dismissBatchSuggestion}>
            ✗ 忽略
          </Button>
        </div>
      </div>
      {s.summary && <p className="text-[11px] text-purple-700">{s.summary}</p>}
      <div className="space-y-1">
        {s.proposals.map((p, i) => (
          <div key={i} className="rounded bg-white p-2 text-xs text-gray-800">
            <div className="mb-0.5 text-[11px] font-medium text-purple-700">
              {FIELD_LABEL[p.field] ?? p.field}
              {p.conflicts_with ? `  · ⚠ 覆盖原「${p.conflicts_with}」` : ""}
            </div>
            <div>{p.text}</div>
            {(p.applies_to ?? []).length > 0 && (
              <div className="mt-0.5 text-[11px] text-gray-400">
                建议也应用到:{p.applies_to.map((f) => FIELD_LABEL[f] ?? f).join("、")}
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="text-[11px] text-purple-600">
        采纳后条目会进入上方「整改提案」区,可勾选分发到其他环节({currentBucket === "chapter" ? "弧线大纲 / Scene beats" : currentBucket === "arc_outline" ? "章节正文 / Scene beats" : "章节正文 / 弧线大纲"})再应用。
      </p>
    </section>
  );
}
