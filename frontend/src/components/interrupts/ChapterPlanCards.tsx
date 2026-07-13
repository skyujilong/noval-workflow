// 章节规划(远端锚点) 结构化只读展示：把 human_review 抽屉里 draft（ChapterPlanItem[] JSON 字符串）
// 渲染成每章一张卡片，五字段（chapter/purpose/key_turn/ending_hook/intensity）分区可扫，
// 并用底色 chip 区分「已锁定历史段」与「新规划段」；intensity 档位带色标。
// 顶部加档位分布统计 + 节奏塌陷/主角被动/套路钩子三类软警告。
// JSON 解析失败时降级为原文 <pre> + 顶部黄条警告，与 SceneBeatsCards 同款容错模式。

import type { NovelState } from "../../lib/types";

/** 7 档强度定义，与后端 state.py:ChapterPlanItem.intensity 保持一致 */
const INTENSITY_META: Record<
  string,
  { label: string; cls: string; bar: string; group: "lull" | "build" | "turn" | "spike" }
> = {
  铺垫: { label: "铺垫", cls: "bg-slate-100 text-slate-600 border-slate-200", bar: "bg-slate-400", group: "lull" },
  缓冲: { label: "缓冲", cls: "bg-sky-50 text-sky-700 border-sky-200", bar: "bg-sky-400", group: "lull" },
  回落: { label: "回落", cls: "bg-indigo-50 text-indigo-700 border-indigo-200", bar: "bg-indigo-400", group: "lull" },
  推进: { label: "推进", cls: "bg-gray-100 text-gray-700 border-gray-300", bar: "bg-gray-500", group: "build" },
  小转折: { label: "小转折", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", bar: "bg-emerald-500", group: "turn" },
  大转折: { label: "大转折", cls: "bg-amber-50 text-amber-700 border-amber-300", bar: "bg-amber-500", group: "spike" },
  爆发: { label: "爆发", cls: "bg-rose-50 text-rose-700 border-rose-300", bar: "bg-rose-500", group: "spike" },
};

const INTENSITY_ORDER = ["铺垫", "缓冲", "回落", "推进", "小转折", "大转折", "爆发"];

/** 与后端 state.py:ChapterPlanItem 字段对齐 */
interface ChapterPlanItem {
  chapter: number;
  purpose: string;
  key_turn: string;
  ending_hook: string;
  intensity?: string;
}

interface Props {
  draft: string;
  novelState?: NovelState;
}

function tryParseChapterPlan(raw: string): ChapterPlanItem[] | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  const start = body.indexOf("[");
  const end = body.lastIndexOf("]");
  if (start === -1 || end === -1 || end <= start) return null;
  const jsonStr = body.slice(start, end + 1);
  try {
    const parsed = JSON.parse(jsonStr);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    const first = parsed[0];
    if (typeof first !== "object" || first === null) return null;
    if (!("chapter" in first) && !("purpose" in first)) return null;
    return parsed as ChapterPlanItem[];
  } catch {
    return null;
  }
}

function chapterSequenceIssues(items: ChapterPlanItem[]): string[] {
  const issues: string[] = [];
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1].chapter;
    const cur = items[i].chapter;
    if (typeof prev !== "number" || typeof cur !== "number") continue;
    if (cur !== prev + 1) issues.push(`第 ${i + 1} 项 chapter=${cur}，应为 ${prev + 1}`);
  }
  return issues;
}

function missingFieldCount(items: ChapterPlanItem[]): number {
  let n = 0;
  for (const it of items) {
    if (!it.purpose?.trim()) n++;
    if (!it.key_turn?.trim()) n++;
    if (!it.ending_hook?.trim()) n++;
  }
  return n;
}

/** 套话/套路检测模式 */
const LAZY_KEY_TURN_PATTERNS = [
  /无强转折[，,]?\s*以.{0,8}铺垫为主/,
  /^无[，,]?\s*$/,
  /^略$/,
  /^见后续$/,
  /^待定$/,
];
const LAZY_HOOK_PATTERNS = [
  /脚步声传来/,
  /一道(黑|身|人影)(闪|出|掠|过)/,
  /突然出现了?/,
  /等待他(们)?的是/,
  /(看到|望着|看见)(了)?(眼前|这)(一幕|景象|一切).*(震惊|惊呆|不敢置信)/,
  /故事(才|还)(刚刚|远没)开始/,
  /接下来(会|又)(发生|是)/,
];

interface Issue {
  level: "error" | "warn";
  msg: string;
}

function detectIssues(items: ChapterPlanItem[], writtenUpto: number): {
  warnings: Issue[];
  intensityCount: Record<string, number>;
} {
  const warnings: Issue[] = [];
  const freshItems = items.filter((it) => it.chapter > writtenUpto);
  const intensityCount: Record<string, number> = {};
  for (const it of freshItems) {
    const k = it.intensity || "";
    intensityCount[k] = (intensityCount[k] || 0) + 1;
  }
  const unknown = freshItems.filter((it) => !it.intensity || !INTENSITY_META[it.intensity]);
  const spikeCount = (intensityCount["爆发"] || 0) + (intensityCount["大转折"] || 0);
  const smallTurnCount = intensityCount["小转折"] || 0;
  const nFresh = freshItems.length;

  if (unknown.length > 0) {
    warnings.push({ level: "error", msg: `${unknown.length} 条 intensity 非 7 档枚举值` });
  }

  if (nFresh >= 8) {
    const spikeRatio = spikeCount / nFresh;
    if (spikeRatio > 0.4) warnings.push({ level: "warn", msg: `爆发/大转折占比 ${(spikeRatio * 100).toFixed(0)}%（>35%），节奏偏挤` });
    else if (spikeRatio < 0.1) warnings.push({ level: "warn", msg: `爆发/大转折占比 ${(spikeRatio * 100).toFixed(0)}%（<14%），高潮不足` });
    if (smallTurnCount < Math.max(2, Math.floor(nFresh / 8))) {
      warnings.push({ level: "warn", msg: `小转折（小爽点）${smallTurnCount} 个偏少，建议每 5-8 章 1 次` });
    }
  }

  // 连续档位与主角能动性检测
  let maxLullStreak = 0, curLull = 0;
  let maxSpikeStreak = 0, curSpike = 0;
  let passiveStreak = 0, maxPassive = 0;
  let winSince = 0, maxGapWin = 0;

  for (const it of freshItems) {
    const meta = INTENSITY_META[it.intensity || ""];
    const isLull = meta?.group === "lull";
    const isSpike = meta?.group === "spike";
    const isWin = isSpike || it.intensity === "小转折" ||
      /(打脸|反杀|胜|震退|获|揭露|突破|反制|震惊|秒|击退|压制)/.test(it.key_turn || "");
    const isPassive =
      /(被|遭|受|刁难|驳回|拒绝|嘲笑|欺辱|歧视|压制|扣押|调查|诬陷|追杀|驱赶|污蔑|举报)/.test(it.key_turn || "") && !isWin;
    curLull = isLull ? curLull + 1 : 0;
    curSpike = isSpike ? curSpike + 1 : 0;
    winSince = isWin ? 0 : winSince + 1;
    passiveStreak = isPassive ? passiveStreak + 1 : 0;
    maxLullStreak = Math.max(maxLullStreak, curLull);
    maxSpikeStreak = Math.max(maxSpikeStreak, curSpike);
    maxGapWin = Math.max(maxGapWin, winSince);
    maxPassive = Math.max(maxPassive, passiveStreak);
  }
  if (maxLullStreak >= 3) warnings.push({ level: "warn", msg: `连续 ${maxLullStreak} 章铺垫/缓冲/回落，节奏塌陷` });
  if (maxSpikeStreak >= 3) warnings.push({ level: "warn", msg: `连续 ${maxSpikeStreak} 章爆发/大转折，节奏窒息` });
  if (maxPassive >= 3) warnings.push({ level: "error", msg: `主角连续 ${maxPassive} 章被动承压，存在虐主风险` });
  if (maxGapWin >= 6) warnings.push({ level: "warn", msg: `主角已连续 ${maxGapWin} 章无小胜/展示，爽点不足` });

  // 套话/套路钩子
  const lazyKeyTurns: number[] = [];
  const lazyHooks: number[] = [];
  for (const it of freshItems) {
    if (LAZY_KEY_TURN_PATTERNS.some((p) => p.test(it.key_turn || ""))) lazyKeyTurns.push(it.chapter);
    if (LAZY_HOOK_PATTERNS.some((p) => p.test(it.ending_hook || ""))) lazyHooks.push(it.chapter);
  }
  if (lazyKeyTurns.length > 0) {
    warnings.push({
      level: "error",
      msg: `${lazyKeyTurns.length} 条 key_turn 套话：第 ${lazyKeyTurns.slice(0, 5).join(",")}${lazyKeyTurns.length > 5 ? "..." : ""} 章需改为具体事件`,
    });
  }
  if (lazyHooks.length > 0) {
    warnings.push({
      level: "warn",
      msg: `${lazyHooks.length} 条 ending_hook 套路（脚步声/黑影类）：第 ${lazyHooks.slice(0, 5).join(",")}${lazyHooks.length > 5 ? "..." : ""} 章建议改为具体信息点`,
    });
  }

  return { warnings, intensityCount };
}

function FieldCell({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <div className="mb-0.5 text-xs font-medium text-gray-500">{label}</div>
      <div className={"text-sm leading-snug whitespace-pre-wrap " + (warn ? "text-red-600" : "text-gray-800")}>
        {value?.trim() ? value : <em className="text-gray-300">（空）</em>}
      </div>
    </div>
  );
}

function ChapterCard({ item, locked }: { item: ChapterPlanItem; locked: boolean }) {
  const intensity = item.intensity || "";
  const meta = INTENSITY_META[intensity];
  const kt = item.key_turn || "";
  const hk = item.ending_hook || "";
  const lazyKt = LAZY_KEY_TURN_PATTERNS.some((p) => p.test(kt));
  const lazyHook = LAZY_HOOK_PATTERNS.some((p) => p.test(hk));
  return (
    <div className={"rounded-lg border shadow-sm " + (locked ? "border-gray-200 bg-gray-50" : "border-gray-200 bg-white")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="text-sm font-semibold text-gray-800">第 {item.chapter} 章</div>
        {meta ? (
          <span className={`rounded border px-1.5 py-0.5 text-xs ${meta.cls}`}>{meta.label}</span>
        ) : intensity ? (
          <span className="rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-xs text-red-700" title="intensity 非 7 档枚举">
            {intensity} ⚠
          </span>
        ) : (
          <span className="rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">缺档位</span>
        )}
        {locked ? (
          <span className="rounded border border-gray-300 bg-gray-200 px-1.5 py-0.5 text-xs text-gray-600">已写就</span>
        ) : (
          <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">新规划</span>
        )}
      </div>
      <div className="space-y-2 px-3 py-2">
        <FieldCell label="本章目标" value={item.purpose} />
        <FieldCell label="关键事件" value={kt + (lazyKt ? "  ⚠️ 套话需改写" : "")} warn={lazyKt} />
        <FieldCell label="章末钩子" value={hk + (lazyHook ? "  ⚠️ 套路钩子建议改具体" : "")} warn={lazyHook} />
      </div>
    </div>
  );
}

function IntensityBar({ intensityCount, total }: { intensityCount: Record<string, number>; total: number }) {
  if (total <= 0) return null;
  return (
    <div className="flex w-full overflow-hidden rounded border border-gray-200 h-5 text-[10px]">
      {INTENSITY_ORDER.map((k) => {
        const c = intensityCount[k] || 0;
        if (c === 0) return null;
        const meta = INTENSITY_META[k];
        const w = (c / total) * 100;
        return (
          <div key={k} className={`flex items-center justify-center ${meta.bar} text-white font-medium`} style={{ width: `${w}%` }} title={`${meta.label} ${c}章`}>
            {w >= 10 ? `${meta.label}${c}` : ""}
          </div>
        );
      })}
    </div>
  );
}

export function ChapterPlanCards({ draft, novelState }: Props) {
  const items = tryParseChapterPlan(draft);

  if (!items) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ 无法解析为结构化 chapter_plan（可能是 LLM 输出格式错误）。以原始文本形式展示,建议提修改意见让 AI 重生成为合规 JSON。
        </div>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs leading-relaxed text-gray-700">
          {draft || "（无草稿内容）"}
        </pre>
      </div>
    );
  }

  const writtenUpto = novelState?.total_chapters_written ?? 0;
  const lockedCount = items.filter((it) => it.chapter <= writtenUpto).length;
  const newCount = items.length - lockedCount;
  const freshItems = items.filter((it) => it.chapter > writtenUpto);
  const seqIssues = chapterSequenceIssues(items);
  const missing = missingFieldCount(items);
  const { warnings, intensityCount } = detectIssues(items, writtenUpto);
  const errorCount = warnings.filter((w) => w.level === "error").length;
  const warnCount = warnings.filter((w) => w.level === "warn").length;

  return (
    <div className="space-y-3">
      {/* 顶部摘要：章数 / 锁定vs新增 / 档位分布条 / 软校验警示 */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          <span className="rounded bg-gray-100 px-2 py-0.5">共 {items.length} 章</span>
          {writtenUpto > 0 && (
            <>
              <span className="rounded border border-gray-300 bg-gray-100 px-2 py-0.5 text-gray-600">已锁定 {lockedCount} 章</span>
              <span className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-blue-700">新规划 {newCount} 章</span>
            </>
          )}
          {seqIssues.length > 0 && (
            <span className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700" title={seqIssues.join("；")}>
              ⚠ 章号非连续升序（{seqIssues.length} 处）
            </span>
          )}
          {missing > 0 && (
            <span className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-amber-700">⚠ 有 {missing} 个字段为空</span>
          )}
          {errorCount > 0 && (
            <span className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700">❌ {errorCount} 项硬性问题</span>
          )}
          {warnCount > 0 && (
            <span className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-amber-700">⚠ {warnCount} 项节奏提醒</span>
          )}
        </div>

        {/* 档位分布条 + 图例 */}
        {freshItems.length > 0 && (
          <div className="space-y-1">
            <IntensityBar intensityCount={intensityCount} total={freshItems.length} />
            <div className="flex flex-wrap gap-2 text-[10px] text-gray-500">
              {INTENSITY_ORDER.map((k) => {
                const c = intensityCount[k] || 0;
                const meta = INTENSITY_META[k];
                return (
                  <span key={k} className="inline-flex items-center gap-1">
                    <span className={`inline-block h-2 w-2 rounded ${meta.bar}`} />
                    {meta.label} {c}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {/* 警示清单 */}
        {warnings.length > 0 && (
          <ul className="space-y-1 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs">
            {warnings.map((w, i) => (
              <li key={i} className={w.level === "error" ? "text-red-700" : "text-amber-800"}>
                {w.level === "error" ? "❌ " : "⚠ "}{w.msg}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 卡片列表 */}
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
        {items.map((it, i) => (
          <ChapterCard key={`${it.chapter}-${i}`} item={it} locked={writtenUpto > 0 && it.chapter <= writtenUpto} />
        ))}
      </div>
    </div>
  );
}
