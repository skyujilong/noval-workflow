// 分卷规划(volumes) 结构化只读展示：human_review 抽屉在 review_type=volumes 时展示 draft
// （Volume[] JSON 字符串）为每卷一张卡片。前端**只读**——用户想改仍走「提出修改意见」文本
// 打回重跑，与 chapter_plan/scene_beats 审核路径一致。
//
// 弹性 range 语义：target_min/target_max 是**章数**(数量,软约束)；卷内章号窗口 =
// [chapter_start, chapter_start + target_max - 1]。actual_end 只有 VOLUME_BOUNDARY_GATE
// 用户点「在此收卷」才写入,抽取阶段一律为 null,故此展示不呈现 actual_end。
//
// JSON 解析失败降级为原文 <pre> + 黄条警告，与 ChapterPlanCards/SceneBeatsCards 同款。

import type { Volume } from "../../lib/types";

interface Props {
  draft: string;
}

/** 宽松解析：允许 markdown 围栏、允许前后冗余文本、只提取首个 [...] 数组。 */
function tryParseVolumes(raw: string): Volume[] | null {
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
    // 关键字段任一存在即视为 volumes 数组（宽松，抽取阶段字段齐全，运行时可能缺 actual_end）
    if (!("index" in first) && !("chapter_start" in first)) return null;
    return parsed as Volume[];
  } catch {
    return null;
  }
}

/** 卷内章号窗口 = [chapter_start, chapter_start + target_max - 1] */
function chapterWindow(v: Volume): [number, number] {
  return [v.chapter_start, v.chapter_start + v.target_max - 1];
}

/** 校验拼接规则 & range 合法性（同后端 save_volumes）——供顶部软警告。 */
function detectIssues(volumes: Volume[]): string[] {
  const issues: string[] = [];
  let nextExpectedStart = 1;
  for (let i = 0; i < volumes.length; i++) {
    const v = volumes[i];
    const label = `第 ${i + 1} 卷`;
    if (v.index !== i + 1) issues.push(`${label} index=${v.index}，应为 ${i + 1}`);
    if (v.chapter_start !== nextExpectedStart) {
      issues.push(`${label} chapter_start=${v.chapter_start}，应为 ${nextExpectedStart}（拼接规则不符）`);
    }
    if (v.target_min <= 0 || v.target_max <= 0) {
      issues.push(`${label} target_min/target_max 必须 > 0`);
    }
    if (v.target_min > v.target_max) {
      issues.push(`${label} target_min=${v.target_min} > target_max=${v.target_max}`);
    }
    nextExpectedStart = v.chapter_start + v.target_max;
  }
  return issues;
}

function StatusBadge({ status }: { status: Volume["status"] }) {
  const map: Record<Volume["status"], { label: string; cls: string }> = {
    planning: { label: "未开启", cls: "border-gray-200 bg-gray-50 text-gray-500" },
    in_progress: { label: "进行中", cls: "border-blue-300 bg-blue-50 text-blue-700" },
    closed: { label: "已收卷 ✓", cls: "border-green-300 bg-green-50 text-green-700" },
  };
  const meta = map[status] ?? { label: status, cls: "border-red-300 bg-red-50 text-red-700" };
  return <span className={`rounded border px-1.5 py-0.5 text-xs ${meta.cls}`}>{meta.label}</span>;
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-0.5 text-xs font-medium text-gray-500">{label}</div>
      <div className="text-sm leading-snug whitespace-pre-wrap text-gray-800">
        {value?.trim() ? value : <em className="text-gray-300">（空）</em>}
      </div>
    </div>
  );
}

function VolumeCard({ volume, isLast }: { volume: Volume; isLast: boolean }) {
  const [winStart, winEnd] = chapterWindow(volume);
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="text-sm font-semibold text-gray-800">
          卷 {volume.index}
        </div>
        <span className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600">
          第 {volume.chapter_start} 章起 · 目标 {volume.target_min}-{volume.target_max} 章
        </span>
        <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
          窗口 [{winStart}, {winEnd}]
        </span>
        <StatusBadge status={volume.status} />
        {volume.actual_end != null && (
          <span className="rounded border border-green-300 bg-green-50 px-1.5 py-0.5 text-[10px] text-green-700">
            实际收卷第 {volume.actual_end} 章
          </span>
        )}
      </div>
      <div className="space-y-2 px-3 py-2">
        <FieldRow label="卷名" value={volume.title} />
        <FieldRow label="本卷主线" value={volume.summary} />
        <FieldRow
          label={isLast ? "卷尾 setup（终卷可空）" : "卷尾 setup（为下一卷埋钩）"}
          value={volume.setup_for_next}
        />
      </div>
    </div>
  );
}

export function VolumesReviewCards({ draft }: Props) {
  const volumes = tryParseVolumes(draft);

  if (!volumes) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ 无法解析为结构化分卷规划（可能是 LLM 输出格式错误）。以原始文本展示，可提修改意见让 AI 重生成合规 JSON。
        </div>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs leading-relaxed text-gray-700">
          {draft || "（无草稿内容）"}
        </pre>
      </div>
    );
  }

  const issues = detectIssues(volumes);
  const totalChapters = volumes.reduce((s, v) => s + v.target_max, 0);
  const [firstStart] = chapterWindow(volumes[0]);
  const [, lastEnd] = chapterWindow(volumes[volumes.length - 1]);

  return (
    <div className="space-y-3">
      {/* 顶部摘要 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">共 {volumes.length} 卷</span>
        <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-gray-600">
          总章数（target_max 累加）{totalChapters}
        </span>
        <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-gray-600">
          整书窗口 [{firstStart}, {lastEnd}]
        </span>
        {issues.length > 0 && (
          <span
            className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700"
            title={issues.join("；")}
          >
            ⚠ {issues.length} 项结构问题
          </span>
        )}
      </div>

      {/* 校验问题清单（有则展开） */}
      {issues.length > 0 && (
        <ul className="space-y-1 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {issues.map((msg, i) => (
            <li key={i}>❌ {msg}</li>
          ))}
        </ul>
      )}

      {/* 卷卡片列表 */}
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
        {volumes.map((v, i) => (
          <VolumeCard key={`${v.index}-${i}`} volume={v} isLast={i === volumes.length - 1} />
        ))}
      </div>
    </div>
  );
}
