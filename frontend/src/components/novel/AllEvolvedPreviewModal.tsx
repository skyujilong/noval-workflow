// 预览总体:并排展示三桶 evolved_directives 当前生效内容,让用户看到跨环节全景。
// 跨桶重复条目高亮为琥珀色,提示"这条其实是全局规矩,可考虑整理消解成一份"。
// 只读——写入路径仍走 EvolutionTab 的 apply/reconcile。

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getAllEvolvedDirectives, type AllEvolvedResponse } from "../../lib/langgraph";
import { reviewTypeLabel } from "../../lib/types";

interface Props {
  open: boolean;
  novelName: string;
  genre: string;
  onClose: () => void;
}

// 三桶 → review_type 反查(用于 chip 中文标签)。
const BUCKET_TO_REVIEW_TYPE: Record<string, string> = {
  chapter: "chapter",
  arc_outline: "arc_outline",
  scene_beats: "scene_beats",
};

export function AllEvolvedPreviewModal({ open, novelName, genre, onClose }: Props) {
  const [data, setData] = useState<AllEvolvedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !novelName) return;
    setLoading(true);
    setError(null);
    getAllEvolvedDirectives(novelName, genre)
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [open, novelName, genre]);

  // 把「跨桶重复」这些行做成 Set,渲染每桶时用于高亮。
  const overlapSet = new Set<string>(
    (data?.cross_bucket_overlaps ?? []).map((o) => o.text)
  );

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-6xl">
        <DialogHeader>
          <DialogTitle>预览总体历史整改要点 · {novelName || "未命名"}</DialogTitle>
          <DialogDescription>
            并排展示三个环节各自沉淀的整改;琥珀色高亮＝该条在多个环节都出现,可考虑合并为全局规矩。
          </DialogDescription>
        </DialogHeader>

        {loading && <p className="text-sm text-gray-500">加载中…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {data && (
          <div className="grid grid-cols-3 gap-3">
            {(["chapter", "arc_outline", "scene_beats"] as const).map((bucket) => (
              <BucketColumn
                key={bucket}
                bucket={bucket}
                text={data[bucket]}
                overlapSet={overlapSet}
              />
            ))}
          </div>
        )}

        {data && data.cross_bucket_overlaps.length > 0 && (
          <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            检测到 <b>{data.cross_bucket_overlaps.length}</b> 条整改在多个环节重复出现——
            可考虑在其中一个环节整理消解,或分发到目标环节后从其他环节移除,减少冗余。
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function BucketColumn({
  bucket,
  text,
  overlapSet,
}: {
  bucket: string;
  text: string;
  overlapSet: Set<string>;
}) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const reviewType = BUCKET_TO_REVIEW_TYPE[bucket] ?? bucket;
  const label = reviewTypeLabel(reviewType);
  return (
    <div className="rounded border border-gray-200 bg-white">
      <div className="border-b border-gray-100 bg-gray-50 px-3 py-2 text-sm font-medium text-gray-700">
        {label}
        <span className="ml-2 text-xs text-gray-400">({lines.length} 条)</span>
      </div>
      <div className="max-h-[60vh] overflow-y-auto p-2 text-xs leading-relaxed">
        {lines.length === 0 && (
          <p className="text-gray-400">(暂无沉淀)</p>
        )}
        <ul className="space-y-1">
          {lines.map((line, i) => (
            <li
              key={i}
              className={
                overlapSet.has(line)
                  ? "rounded bg-amber-50 px-2 py-1 text-amber-900"
                  : "px-2 py-1 text-gray-700"
              }
              title={overlapSet.has(line) ? "该条在多个环节重复" : undefined}
            >
              {line}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
