// 分卷规划(volumes) 多卷只读展示：human_review 抽屉在 review_type=volumes 但无 threadId（降级
// 路径）时展示 draft 为卡片列表。前端**只读**——用户想改走「提出修改意见」文本打回重跑。
// 前瞻队列架构：一次规划「1 激活卷 + N 前瞻草稿卷」，草稿是对象 {"volumes":[激活卷, 草稿1, ...]}。
// 激活卷含 title/summary/setup_for_next/chapters；草稿卷只 title/summary/setup_for_next。
//
// JSON 解析失败降级为原文 <pre> + 黄条警告，与 ChapterPlanCards/SceneBeatsCards 同款。

interface Props {
  draft: string;
}

interface VolumeCard {
  title: string;
  summary: string;
  setup_for_next: string;
  chapters: number | null; // 仅激活卷（第 0 项）有
}

/** 宽松解析多卷草稿 → VolumeCard[]：支持对象 {volumes:[...]} 或裸数组，允许 markdown 围栏/冗余文本。 */
function tryParseVolumeCards(raw: string): VolumeCard[] | null {
  if (!raw || !raw.trim()) return null;
  const fenced = raw.trim().match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = (fenced ? fenced[1] : raw).trim();
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    const objStart = body.indexOf("{");
    const arrStart = body.indexOf("[");
    try {
      if (arrStart !== -1 && (objStart === -1 || arrStart < objStart)) {
        parsed = JSON.parse(body.slice(arrStart, body.lastIndexOf("]") + 1));
      } else if (objStart !== -1) {
        parsed = JSON.parse(body.slice(objStart, body.lastIndexOf("}") + 1));
      } else {
        return null;
      }
    } catch {
      return null;
    }
  }
  const arr: unknown = Array.isArray(parsed)
    ? parsed
    : typeof parsed === "object" &&
        parsed !== null &&
        Array.isArray((parsed as Record<string, unknown>).volumes)
      ? (parsed as Record<string, unknown>).volumes
      : null;
  if (!Array.isArray(arr) || arr.length === 0) return null;
  return arr.map((item, i): VolumeCard => {
    const o = (typeof item === "object" && item !== null ? item : {}) as Record<string, unknown>;
    return {
      title: typeof o.title === "string" ? o.title : "",
      summary: typeof o.summary === "string" ? o.summary : "",
      setup_for_next: typeof o.setup_for_next === "string" ? o.setup_for_next : "",
      chapters: i === 0 && typeof o.chapters === "number" ? o.chapters : null,
    };
  });
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
  const vols = tryParseVolumeCards(draft);

  if (!vols) {
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

  const active = vols[0];
  const drafts = vols.slice(1);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">
          本次规划：1 激活 + {drafts.length} 前瞻草稿
        </span>
        <span className="rounded border border-gray-200 bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">
          卷号 / 起止章号由系统权威赋值
        </span>
      </div>

      {/* 激活卷（即将展开）*/}
      <div className="rounded-lg border border-blue-200 bg-blue-50/40 px-3 py-2 shadow-sm">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className="rounded bg-blue-600 px-2 py-0.5 text-[10px] font-medium text-white">
            激活卷 · 即将展开
          </span>
          <span className="rounded border border-gray-200 bg-white px-2 py-0.5 text-[10px] text-gray-600">
            本卷章数 {active.chapters ?? "（未给）"}
          </span>
        </div>
        <div className="space-y-2">
          <FieldRow label="卷名" value={active.title} />
          <FieldRow label="本卷主线" value={active.summary} />
          <FieldRow label="卷尾 setup（为下一卷埋钩；终卷可空）" value={active.setup_for_next} />
        </div>
      </div>

      {/* 前瞻草稿卷（只给方向，未锁章号）*/}
      {drafts.map((d, i) => (
        <div key={i} className="rounded-lg border border-dashed border-gray-300 bg-white px-3 py-2 shadow-sm">
          <div className="mb-1">
            <span className="rounded bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
              前瞻草稿 {i + 1} · 未锁章号
            </span>
          </div>
          <div className="space-y-2">
            <FieldRow label="卷名" value={d.title} />
            <FieldRow label="本卷主线" value={d.summary} />
            <FieldRow label="卷尾 setup" value={d.setup_for_next} />
          </div>
        </div>
      ))}
    </div>
  );
}
