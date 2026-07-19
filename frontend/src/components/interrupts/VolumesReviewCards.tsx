// 分卷规划(volumes) 单卷只读展示：human_review 抽屉在 review_type=volumes 但无 threadId（降级
// 路径）时展示 draft（单卷 JSON 对象）为一张卡片。前端**只读**——用户想改走「提出修改意见」文本
// 打回重跑。滚动生成卷架构下一次只规划一卷，草稿只含 title/summary/setup_for_next/chapters。
//
// JSON 解析失败降级为原文 <pre> + 黄条警告，与 ChapterPlanCards/SceneBeatsCards 同款。

interface Props {
  draft: string;
}

interface VolumeDraft {
  title: string;
  summary: string;
  setup_for_next: string;
  chapters: number | null;
}

/** 宽松解析单卷对象：允许 markdown 围栏、前后冗余文本，只提取首个 {...}。 */
function tryParseVolumeDraft(raw: string): VolumeDraft | null {
  if (!raw || !raw.trim()) return null;
  const trimmed = raw.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1].trim() : trimmed;
  const start = body.indexOf("{");
  const end = body.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const o = JSON.parse(body.slice(start, end + 1)) as Record<string, unknown>;
    if (typeof o !== "object" || o === null) return null;
    // 关键字段任一存在即视为单卷草稿（宽松）
    if (!("title" in o) && !("chapters" in o) && !("summary" in o)) return null;
    return {
      title: typeof o.title === "string" ? o.title : "",
      summary: typeof o.summary === "string" ? o.summary : "",
      setup_for_next: typeof o.setup_for_next === "string" ? o.setup_for_next : "",
      chapters: typeof o.chapters === "number" ? o.chapters : null,
    };
  } catch {
    return null;
  }
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

export function VolumesReviewCards({ draft }: Props) {
  const vol = tryParseVolumeDraft(draft);

  if (!vol) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ 无法解析为结构化单卷规划（可能是 LLM 输出格式错误）。以原始文本展示，可提修改意见让 AI 重生成合规 JSON 对象。
        </div>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs leading-relaxed text-gray-700">
          {draft || "（无草稿内容）"}
        </pre>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">本次规划：1 卷</span>
        <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-gray-600">
          本卷章数 {vol.chapters ?? "（未给）"}
        </span>
        <span className="rounded border border-gray-200 bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">
          卷号 / 起止章号由系统权威赋值
        </span>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-sm">
        <div className="space-y-2">
          <FieldRow label="卷名" value={vol.title} />
          <FieldRow label="本卷主线" value={vol.summary} />
          <FieldRow label="卷尾 setup（为下一卷埋钩；终卷可空）" value={vol.setup_for_next} />
        </div>
      </div>
    </div>
  );
}
