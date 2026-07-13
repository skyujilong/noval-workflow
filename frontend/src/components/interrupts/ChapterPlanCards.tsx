// 章节规划(远端锚点) 结构化只读展示：把 human_review 抽屉里 draft（ChapterPlanItem[] JSON 字符串）
// 渲染成每章一张卡片，四字段（chapter/purpose/key_turn/ending_hook）分区可扫，
// 并用底色 chip 区分「已锁定历史段」与「新规划段」。
// JSON 解析失败时降级为原文 <pre> + 顶部黄条警告，与 SceneBeatsCards 同款容错模式。

import type { NovelState } from "../../lib/types";

/** 与后端 state.py:ChapterPlanItem 字段对齐（章号 1-based，其余中文字段） */
interface ChapterPlanItem {
  chapter: number;
  purpose: string;
  key_turn: string;
  ending_hook: string;
}

interface Props {
  /** LLM 生成的原始 draft 字符串（应为 JSON 数组）。解析失败时降级到纯文本视图。 */
  draft: string;
  /** 父图 NovelState 快照：用于取 total_chapters_written 区分锁定段 vs 新增段。 */
  novelState?: NovelState;
}

/**
 * 解析 draft：容忍 LLM 常见的 markdown 围栏（```json ... ```）+ 首尾杂散文字。
 * 与 SceneBeatsCards.tryParseBeats 同款思路——只读展示无需 fail-fast，
 * 失败降级到纯文本让用户看原文自己提修改意见。
 */
function tryParseChapterPlan(raw: string): ChapterPlanItem[] | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  // 剥围栏
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  // 定位第一个 [ 到最后一个 ]，兼容首尾杂散文字
  const start = body.indexOf("[");
  const end = body.lastIndexOf("]");
  if (start === -1 || end === -1 || end <= start) return null;
  const jsonStr = body.slice(start, end + 1);
  try {
    const parsed = JSON.parse(jsonStr);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    // 至少验第一元素形态像 ChapterPlanItem（有 chapter 或 purpose 之一）
    const first = parsed[0];
    if (typeof first !== "object" || first === null) return null;
    if (!("chapter" in first) && !("purpose" in first)) return null;
    return parsed as ChapterPlanItem[];
  } catch {
    return null;
  }
}

/** 章号连续升序软校验——后端已有硬约束（nodes/chapter_plan.py:86-92），
 *  前端二次校验只为在极端情况（LLM 违约或数据损坏）下给审稿者显式提示。 */
function chapterSequenceIssues(items: ChapterPlanItem[]): string[] {
  const issues: string[] = [];
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1].chapter;
    const cur = items[i].chapter;
    if (typeof prev !== "number" || typeof cur !== "number") continue;
    if (cur !== prev + 1) {
      issues.push(`第 ${i + 1} 项 chapter=${cur}，应为 ${prev + 1}`);
    }
  }
  return issues;
}

/** 字段缺失软校验——purpose/key_turn/ending_hook 空字符串视为缺失。 */
function missingFieldCount(items: ChapterPlanItem[]): number {
  let n = 0;
  for (const it of items) {
    if (!it.purpose?.trim()) n++;
    if (!it.key_turn?.trim()) n++;
    if (!it.ending_hook?.trim()) n++;
  }
  return n;
}

/** 通用 KV 展示：label 小灰字 + value 大字，空值渲染为占位斜体。
 *  复刻 SceneBeatsCards 里同款函数——为一次复用不破坏兄弟组件的封装。 */
function FieldCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-0.5 text-xs font-medium text-gray-500">{label}</div>
      <div className="text-sm text-gray-800 leading-snug whitespace-pre-wrap">
        {value?.trim() ? value : <em className="text-gray-300">（空）</em>}
      </div>
    </div>
  );
}

/** 单章卡片：卡片头（第 N 章 + 锁定/新增 chip）+ 三字段区。 */
function ChapterCard({ item, locked }: { item: ChapterPlanItem; locked: boolean }) {
  return (
    <div
      className={
        "rounded-lg border shadow-sm " +
        (locked ? "border-gray-200 bg-gray-50" : "border-gray-200 bg-white")
      }
    >
      <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="text-sm font-semibold text-gray-800">第 {item.chapter} 章</div>
        {locked ? (
          <span className="rounded border border-gray-300 bg-gray-200 px-1.5 py-0.5 text-xs text-gray-600">
            已写就
          </span>
        ) : (
          <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">
            新规划
          </span>
        )}
      </div>
      <div className="space-y-2 px-3 py-2">
        <FieldCell label="本章目标" value={item.purpose} />
        <FieldCell label="关键转折" value={item.key_turn} />
        <FieldCell label="章末钩子" value={item.ending_hook} />
      </div>
    </div>
  );
}

export function ChapterPlanCards({ draft, novelState }: Props) {
  const items = tryParseChapterPlan(draft);

  // 降级视图：LLM 输出无法解析成 JSON 数组时，展示原文并提醒
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

  // 锁定段判定：total_chapters_written 存在时按 chapter <= 阈值判为锁定；缺失时全部视作新增
  const writtenUpto = novelState?.total_chapters_written ?? 0;
  const lockedCount = items.filter((it) => it.chapter <= writtenUpto).length;
  const newCount = items.length - lockedCount;

  const seqIssues = chapterSequenceIssues(items);
  const missing = missingFieldCount(items);

  return (
    <div className="space-y-3">
      {/* 顶部摘要：章数 / 锁定vs新增分区 / 软校验警示条 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">共 {items.length} 章</span>
        {writtenUpto > 0 && (
          <>
            <span className="rounded border border-gray-300 bg-gray-100 px-2 py-0.5 text-gray-600">
              已锁定 {lockedCount} 章
            </span>
            <span className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-blue-700">
              新规划 {newCount} 章
            </span>
          </>
        )}
        {seqIssues.length > 0 && (
          <span
            className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700"
            title={seqIssues.join("；")}
          >
            ⚠ 章号非连续升序（{seqIssues.length} 处）
          </span>
        )}
        {missing > 0 && (
          <span className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-amber-700">
            ⚠ 有 {missing} 个字段为空
          </span>
        )}
      </div>

      {/* 卡片列表 */}
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
        {items.map((it, i) => (
          <ChapterCard
            key={`${it.chapter}-${i}`}
            item={it}
            locked={writtenUpto > 0 && it.chapter <= writtenUpto}
          />
        ))}
      </div>
    </div>
  );
}
