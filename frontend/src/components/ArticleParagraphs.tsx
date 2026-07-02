// 正文按段落渲染：小说正文用单个换行分段，而 Markdown 会把单换行并入同一段，
// 导致整篇正文塌成一个 <p>，父级的段落缩进/间距（[&_p]:…）也就只作用到那一段。
// 这里直接按换行切分，每个非空行渲染为独立 <p>，让每段都真正成段。
// 只渲染 <p> 片段、不带外层容器，故父级现有的 [&_p]:… 样式可直接生效。

interface Props {
  /** 原始正文，段落之间以换行（\n）分隔 */
  text: string;
}

export function ArticleParagraphs({ text }: Props) {
  const paragraphs = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  return (
    <>
      {paragraphs.map((paragraph, i) => (
        <p key={i}>{paragraph}</p>
      ))}
    </>
  );
}
