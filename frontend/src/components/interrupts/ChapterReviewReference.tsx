// 章节正文审核时的「参考资料」：近期弧线大纲 + 上一章正文。
// 数据全部取自父图 NovelState 快照（current_arc_outline / all_chapter_titles /
// total_chapters_written / novel_name）——上一章正文只在磁盘，故懒加载复用 files.ts。
// 仅 review_type === "chapter" 时由 HumanReviewForm 渲染。

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { chapterUrl, fetchChapterText } from "../../lib/files";
import type { NovelState } from "../../lib/types";

interface Props {
  novelState: NovelState;
}

export function ChapterReviewReference({ novelState }: Props) {
  const novelName = novelState.novel_name ?? "";
  const arcOutline = (novelState.current_arc_outline ?? "").trim();
  const titles = novelState.all_chapter_titles ?? [];
  // 正在审核的是第 total_chapters_written + 1 章（save_chapter 通过后才自增），
  // 故上一章 = 第 total_chapters_written 章，标题即 all_chapter_titles 的最后一条。
  const prevChapterNum = novelState.total_chapters_written ?? 0;
  const prevTitle = prevChapterNum > 0 ? titles[prevChapterNum - 1] : undefined;

  const hasArc = arcOutline.length > 0;
  const hasPrev = prevChapterNum > 0 && !!prevTitle && !!novelName;

  if (!hasArc && !hasPrev) return null;

  return (
    <div className="space-y-2">
      {hasArc && (
        <details className="rounded border border-gray-200 p-2 text-sm">
          <summary className="cursor-pointer text-gray-600">近期弧线大纲</summary>
          <div className="mt-2 max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
            {arcOutline}
          </div>
        </details>
      )}
      {hasPrev && (
        <PreviousChapterDetails
          novelName={novelName}
          chapterNum={prevChapterNum}
          title={prevTitle as string}
        />
      )}
    </div>
  );
}

interface PreviousChapterProps {
  novelName: string;
  chapterNum: number;
  title: string;
}

function PreviousChapterDetails({ novelName, chapterNum, title }: PreviousChapterProps) {
  // opened 一经置真即保持，确保折叠后再展开不重复请求、内容不丢。
  const [opened, setOpened] = useState(false);
  const { content, loading, error } = usePreviousChapter(novelName, chapterNum, title, opened);

  return (
    <details
      className="rounded border border-gray-200 p-2 text-sm"
      onToggle={(e) => {
        if (e.currentTarget.open) setOpened(true);
      }}
    >
      <summary className="cursor-pointer text-gray-600">
        上一章 · 第{chapterNum}章 {title}
      </summary>
      <div className="mt-2 max-h-[50vh] overflow-y-auto">
        {loading && <div className="text-xs text-gray-400">加载中…</div>}
        {error && <div className="rounded bg-red-50 p-2 text-xs text-red-600">{error}</div>}
        {!loading && !error && content && (
          <div className="text-sm leading-relaxed text-gray-700 [&_p]:[text-indent:2em] [&_p]:mb-4 [&_p]:whitespace-pre-wrap">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
        )}
        {!loading && !error && !content && (
          <div className="text-xs text-gray-400">（无正文内容）</div>
        )}
      </div>
    </details>
  );
}

interface PreviousChapterResult {
  content: string;
  loading: boolean;
  error: string | null;
}

/** 懒加载上一章正文：enabled 为 true 时才按 novelName/chapterNum/title 拉取磁盘文件。 */
function usePreviousChapter(
  novelName: string,
  chapterNum: number,
  title: string,
  enabled: boolean,
): PreviousChapterResult {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    // AbortController：字段变化 / 卸载时取消进行中的请求，避免旧响应覆盖（竞态）
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchChapterText(chapterUrl(novelName, chapterNum, title), controller.signal)
      .then((txt) => setContent(txt))
      .catch((e) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof Error ? e.message : String(e));
        setContent("");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [enabled, novelName, chapterNum, title]);

  return { content, loading, error };
}
