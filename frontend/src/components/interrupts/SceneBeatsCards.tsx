// Scene beats 结构化只读展示：把 human_review 抽屉里 draft（JSON 字符串）渲染成
// 每 beat 一张卡片，device_tags 按分组着色 chip 展示，让"打脸四拍 / 章尾钩 / 伏笔 / 缓冲"
// 一眼可扫。JSON 解析失败时降级为原纯文本视图 + 顶部黄条警告。

// 与后端 prompts/scene_beats.py 的 5 组 device_tag 完全对齐；组标签同名，避免语义漂移。
const TAG_GROUPS = {
  slap: {
    tags: ["slap_taunt", "slap_silence", "slap_crush", "slap_witness"] as const,
    label: "打脸四拍",
    // 红——打脸系是最抢眼的爽点节奏
    cls: "bg-red-50 text-red-700 border-red-200",
  },
  catharsis: {
    tags: ["setup", "buildup", "release"] as const,
    label: "三段式爽感",
    // 蓝——通用节奏，视觉稳定
    cls: "bg-blue-50 text-blue-700 border-blue-200",
  },
  hook: {
    tags: ["hook_opening", "hook_chapter_end"] as const,
    label: "钩子",
    // 紫——钩子是「结构位点」，独立色
    cls: "bg-purple-50 text-purple-700 border-purple-200",
  },
  foreshadow: {
    tags: ["foreshadow_plant", "foreshadow_recover"] as const,
    label: "伏笔",
    // 琥珀——线索感
    cls: "bg-amber-50 text-amber-700 border-amber-200",
  },
  buffer: {
    tags: ["buffer"] as const,
    label: "缓冲",
    // 灰——缓冲是"降节奏"，弱化视觉
    cls: "bg-gray-100 text-gray-600 border-gray-200",
  },
} as const;

const TAG_LABELS: Record<string, string> = {
  setup: "铺陈",
  buildup: "蓄势",
  release: "释放",
  slap_taunt: "嘲讽",
  slap_silence: "沉默",
  slap_crush: "碾压",
  slap_witness: "围观",
  hook_opening: "开篇钩",
  hook_chapter_end: "章尾钩",
  foreshadow_plant: "埋点",
  foreshadow_recover: "回收",
  buffer: "缓冲",
};

function tagStyle(tag: string): string {
  for (const g of Object.values(TAG_GROUPS)) {
    if ((g.tags as readonly string[]).includes(tag)) return g.cls;
  }
  // 越界 tag：用红边显式暴露契约违规，方便审稿时一眼看到
  return "bg-white text-red-600 border-red-400 border-dashed";
}

// 单 beat 里可能出现的字段。后端契约固定 9 项，但字段值可能是空串——渲染时保持字段名可见即可。
interface Beat {
  id?: number;
  scene?: string;
  goal?: string;
  obstacle?: string;
  outcome?: string;
  cost?: string;
  emotion_arc?: string;
  device_tags?: string[];
  target_words?: number;
}

interface Props {
  /** LLM 生成的原始 draft 字符串（应为 JSON 数组）。解析失败时降级到纯文本视图。 */
  draft: string;
}

/**
 * 解析 draft：容忍 LLM 常见的 markdown 围栏（```json ... ```）+ 首尾杂散文字。
 * 与后端 repair_and_parse 的思路一致但简化——前端只做只读展示，解析失败降级即可，
 * 无需 fail-fast（用户可直接看原文 + 提修改意见）。
 */
function tryParseBeats(raw: string): Beat[] | null {
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
    // 至少验第一个元素形态像 beat（有 id 或 scene 或 goal 之一）
    const first = parsed[0];
    if (typeof first !== "object" || first === null) return null;
    return parsed as Beat[];
  } catch {
    return null;
  }
}

/** 打脸四拍在整个 beats 序列里出现是否完整——不完整时抽屉顶部挂红条提醒审稿者。 */
function slapMissing(beats: Beat[]): string[] {
  const seen = new Set<string>();
  for (const b of beats) {
    for (const t of b.device_tags ?? []) {
      if ((TAG_GROUPS.slap.tags as readonly string[]).includes(t)) seen.add(t);
    }
  }
  if (seen.size === 0) return []; // 无打脸桥段——正常，不报
  const missing: string[] = [];
  for (const t of TAG_GROUPS.slap.tags) {
    if (!seen.has(t)) missing.push(t);
  }
  return missing;
}

/** 章尾钩是否落末 beat；开篇钩是否落首 beat。任一违规都返回警告文案。 */
function hookIssues(beats: Beat[]): string[] {
  const issues: string[] = [];
  const last = beats.length - 1;
  beats.forEach((b, i) => {
    for (const t of b.device_tags ?? []) {
      if (t === "hook_chapter_end" && i !== last) {
        issues.push(`章尾钩挂在 beat ${i + 1}（应在末 beat ${last + 1}）`);
      }
      if (t === "hook_opening" && i !== 0) {
        issues.push(`开篇钩挂在 beat ${i + 1}（应在首 beat）`);
      }
    }
  });
  return issues;
}

export function SceneBeatsCards({ draft }: Props) {
  const beats = tryParseBeats(draft);

  if (!beats) {
    // 降级视图：LLM 输出无法解析成 JSON 数组时,展示原文并提醒
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ 无法解析为结构化 beats（可能是 LLM 输出格式错误）。以原始文本形式展示,建议提修改意见让 AI 重生成为合规 JSON。
        </div>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs leading-relaxed text-gray-700">
          {draft || "（无草稿内容）"}
        </pre>
      </div>
    );
  }

  const totalWords = beats.reduce((s, b) => s + (Number(b.target_words) || 0), 0);
  const slapMiss = slapMissing(beats);
  const hookProblems = hookIssues(beats);

  return (
    <div className="space-y-3">
      {/* 顶部摘要：beat 数 / 目标字数累加 / 硬约束违规提醒 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-100 px-2 py-0.5">共 {beats.length} 个 beat</span>
        <span className="rounded bg-gray-100 px-2 py-0.5">累计目标 {totalWords} 字</span>
        {slapMiss.length > 0 && (
          <span className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700">
            打脸四拍不齐：缺 {slapMiss.map((t) => TAG_LABELS[t] ?? t).join(" / ")}
          </span>
        )}
        {hookProblems.map((p, i) => (
          <span key={i} className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-red-700">
            {p}
          </span>
        ))}
      </div>

      {/* Beat 卡片列表 */}
      <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
        {beats.map((b, i) => (
          <BeatCard key={i} beat={b} index={i} isLast={i === beats.length - 1} />
        ))}
      </div>
    </div>
  );
}

function BeatCard({ beat, index, isLast }: { beat: Beat; index: number; isLast: boolean }) {
  const id = beat.id ?? index + 1;
  const tags = beat.device_tags ?? [];

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      {/* 卡片头：编号 + 场景 + 目标字数 */}
      <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-xs text-white">
            #{id}
          </span>
          <span className="text-gray-700">{beat.scene || <em className="text-gray-400">（未填场景）</em>}</span>
          {isLast && <span className="text-xs text-gray-400">· 末 beat</span>}
        </div>
        {beat.target_words !== undefined && (
          <span className="text-xs text-gray-500">目标 {beat.target_words} 字</span>
        )}
      </div>

      {/* device_tags 色标 chip 行 */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b border-gray-100">
          {tags.map((t) => (
            <span
              key={t}
              className={
                "rounded border px-1.5 py-0.5 text-xs font-medium " + tagStyle(t)
              }
              title={t}
            >
              {TAG_LABELS[t] ?? t}
            </span>
          ))}
        </div>
      )}

      {/* 4 字段核心：goal / obstacle / outcome / cost —— 2×2 网格更好扫读 */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 px-3 py-2 text-sm">
        <FieldCell label="目标" value={beat.goal} />
        <FieldCell label="阻碍" value={beat.obstacle} />
        <FieldCell label="结果" value={beat.outcome} />
        <FieldCell label="代价" value={beat.cost} />
      </div>

      {/* 情绪曲线单独一行 */}
      {beat.emotion_arc && (
        <div className="border-t border-gray-100 px-3 py-2 text-xs text-gray-600">
          <span className="font-medium text-gray-500">情绪：</span>
          <span>{beat.emotion_arc}</span>
        </div>
      )}
    </div>
  );
}

function FieldCell({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <div className="mb-0.5 text-xs font-medium text-gray-500">{label}</div>
      <div className="text-sm text-gray-800 leading-snug">
        {value || <em className="text-gray-300">（空）</em>}
      </div>
    </div>
  );
}
