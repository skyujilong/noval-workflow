// 章节文件 URL 构造，镜像 src/novel_workflow/context.py 的 sanitize 规则。
//
// Python context.py:
//   safe_name = re.sub(r'[^\w一-鿿]', '_', novel_name).strip('_')
//   safe_title = re.sub(r'[^\w一-鿿]', '_', title)
//   filename = f"chapter_{num:03d}_{safe_title}.txt"
// 注意 Python re 的 \w 在 str 模式含 Unicode 字母；JS \w 仅 ASCII，
// 故用 Unicode 属性转义 \p{L}\p{N} 等价 Python \w 的 Unicode 行为。

import { API_URL } from "./langgraph";

/** 镜像 context.py 的 sanitize：非（字母/数字/下划线/中文）字符替换为 _ */
function sanitize(s: string): string {
  // \p{L} 字母 \p{N} 数字，等价 Python \w 的 Unicode 语义；再显式保留中文范围与下划线
  return s.replace(/[^\p{L}\p{N}_]/gu, "_");
}

/** 镜像 context.py get_output_dir 的 novel_name 处理：sanitize + 去首尾下划线 */
function safeNovelName(novelName: string): string {
  return sanitize(novelName).replace(/^_+|_+$/g, "");
}

/** 构造章节正文文件 URL */
export function chapterUrl(novelName: string, chapterNum: number, title: string): string {
  const safeNovel = safeNovelName(novelName);
  const safeTitle = sanitize(title);
  const stem = `chapter_${String(chapterNum).padStart(3, "0")}_${safeTitle}.txt`;
  const path = `/output/${safeNovel}/chapters/${stem}`;
  return `${API_URL}${encodeURI(path)}`;
}

/** 构造章节摘要文件 URL */
export function summaryUrl(novelName: string, chapterNum: number, title: string): string {
  const safeNovel = safeNovelName(novelName);
  const safeTitle = sanitize(title);
  const stem = `chapter_${String(chapterNum).padStart(3, "0")}_${safeTitle}.txt`;
  const path = `/output/${safeNovel}/summaries/${stem}`;
  return `${API_URL}${encodeURI(path)}`;
}

/** 读取章节正文文本
 * @param signal 可选 AbortSignal：调用方切换章节/卸载时 abort，取消进行中的请求
 */
export async function fetchChapterText(url: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`读取章节失败 (${res.status})`);
  }
  return res.text();
}
