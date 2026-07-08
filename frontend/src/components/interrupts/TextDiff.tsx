// 高亮 diff 展示（jsdiff 行级）：改前 → 改后 的增删逐块着色。纯展示、无状态。
// 对「实时编辑后的 after」计算，故用户在下方文本框改动会即时反映到 diff。

import { useMemo } from "react";
import { diffLines, type Change } from "diff";

interface Props {
  before: string;
  after: string;
}

export function TextDiff({ before, after }: Props) {
  const parts = useMemo<Change[]>(() => diffLines(before, after), [before, after]);
  const unchanged = parts.every((p) => !p.added && !p.removed);

  return (
    <div className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 font-mono text-[11px] leading-relaxed">
      {unchanged ? (
        <span className="text-gray-400">（与原文一致，无改动）</span>
      ) : (
        parts.map((part, i) => {
          if (part.added) {
            return (
              <span key={i} className="bg-green-100 text-green-800">
                {part.value}
              </span>
            );
          }
          if (part.removed) {
            return (
              <span key={i} className="bg-red-100 text-red-700 line-through">
                {part.value}
              </span>
            );
          }
          return (
            <span key={i} className="text-gray-500">
              {part.value}
            </span>
          );
        })
      )}
    </div>
  );
}
