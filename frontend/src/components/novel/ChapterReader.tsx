// 章节正文阅读视图：左侧章节列表，右侧渲染正文（从 output/<小说名>/chapters/*.txt 读取）。

import { useEffect, useState } from "react";
import { ArticleParagraphs } from "../ArticleParagraphs";
import { chapterUrl, fetchChapterText } from "../../lib/files";
import type { NovelState } from "../../lib/types";

interface Props {
  state: NovelState;
}

export function ChapterReader({ state }: Props) {
  const titles = state.all_chapter_titles ?? [];
  const novelName = state.novel_name ?? "";
  const [selectedIdx, setSelectedIdx] = useState<number>(-1);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedIdx < 0) return;
    if (!novelName) {
      setError("小说名称为空，无法定位章节文件");
      return;
    }
    const title = titles[selectedIdx];
    if (!title) return;
    // AbortController：切换章节或卸载时取消上一个请求，避免旧响应覆盖新内容（竞态）
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchChapterText(chapterUrl(novelName, selectedIdx + 1, title), controller.signal)
      .then((txt) => setContent(txt))
      .catch((e) => {
        // 主动取消视为正常，不更新错误态（避免卸载后 setState）
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e.message);
        setContent("");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedIdx, novelName, titles]);

  if (!novelName) {
    return <div className="p-4 text-sm text-gray-400">尚未开始创作，无章节可读。</div>;
  }
  if (titles.length === 0) {
    return <div className="p-4 text-sm text-gray-400">暂无已完成的章节。</div>;
  }

  return (
    // 自适应父容器高度：由使用方决定尺寸（抽屉里 flex-1 撑满、详情 tab 里包一层固定高度）。
    // 两列各自 overflow-y-auto 依赖父有确定高度，故 min-h-0 防 flex 子项撑破。
    <div className="flex h-full min-h-0">
      {/* 章节列表 */}
      <div className="w-40 overflow-y-auto border-r">
        {titles.map((t, i) => (
          <button
            key={i}
            onClick={() => setSelectedIdx(i)}
            className={
              "block w-full border-b px-2 py-1.5 text-left text-xs hover:bg-gray-50 " +
              (i === selectedIdx ? "bg-blue-50 text-blue-700" : "text-gray-700")
            }
            title={t}
          >
            <span className="mr-1 text-gray-400">第{i + 1}章</span>
            <span className="block truncate">{t}</span>
          </button>
        ))}
      </div>

      {/* 正文 */}
      <div className="flex-1 overflow-y-auto p-4">
        {selectedIdx < 0 && (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            从左侧选择一章阅读
          </div>
        )}
        {selectedIdx >= 0 && loading && (
          <div className="text-sm text-gray-400">加载中…</div>
        )}
        {selectedIdx >= 0 && error && (
          <div className="rounded bg-red-50 p-2 text-sm text-red-600">{error}</div>
        )}
        {selectedIdx >= 0 && !loading && !error && content && (
          <div className="prose prose-sm max-w-none leading-relaxed text-gray-800 [&_p]:[text-indent:2em] [&_p]:mb-4 [&_p]:whitespace-pre-wrap">
            <ArticleParagraphs text={content} />
          </div>
        )}
      </div>
    </div>
  );
}
