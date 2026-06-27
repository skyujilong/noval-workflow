// 镜像 src/novel_workflow/state.py 的状态字段，供前端类型安全访问 thread state。
// 注意：LangGraph 平台返回的 state 实际在 SDK 的 Thread.values 里。

/** 审稿子状态（subgraph.py ReviewSubState）— 仅前端展示用 */
export interface ReviewHistoryEntry {
  role: "human" | "ai";
  content: string;
}

/** NovelState（state.py）— 平台 thread state 的 values 结构 */
export interface NovelState {
  // Phase 0：用户输入
  novel_name: string;
  genre: string;
  writing_style: string;
  target_audience: string;
  core_tone: string;
  chapter_word_count: string;
  total_word_count: string;

  // 子图桥接字段
  system_context: string;
  task_prompt: string;
  current_draft: string;
  review_feedback: string;
  approved: boolean;
  review_type: string;
  llm_review_count: number;

  // Phase 1：基础设定
  core_theme: string;
  world_building: string;
  core_conflicts: string;
  overall_outline: string;
  character_profiles: string;

  // Phase 2：章节写作追踪
  current_batch_titles: string[];
  all_chapter_titles: string[];
  all_chapter_summaries: string[];
  current_chapter_index: number;
  total_chapters_written: number;
  continue_writing: boolean;

  // Phase 2.5：弧线与动态状态库
  current_arc_outline: string;
  character_status: string;
  character_relations: string;
  foreshadowing: string;
  phase_summary: string;

  // 子图扩展字段（部分子图会用到）
  review_history?: ReviewHistoryEntry[];
  llm_review_max?: number;
}

/** 空状态，用于初始展示 */
export const EMPTY_NOVEL_STATE: NovelState = {
  novel_name: "",
  genre: "",
  writing_style: "",
  target_audience: "",
  core_tone: "",
  chapter_word_count: "",
  total_word_count: "",
  system_context: "",
  task_prompt: "",
  current_draft: "",
  review_feedback: "",
  approved: false,
  review_type: "foundation",
  llm_review_count: 0,
  core_theme: "",
  world_building: "",
  core_conflicts: "",
  overall_outline: "",
  character_profiles: "",
  current_batch_titles: [],
  all_chapter_titles: [],
  all_chapter_summaries: [],
  current_chapter_index: 0,
  total_chapters_written: 0,
  continue_writing: true,
  current_arc_outline: "",
  character_status: "",
  character_relations: "",
  foreshadowing: "",
  phase_summary: "",
};

/** review_type → 中文标签（来自 subgraph.py _REVIEW_PROMPTS / _HISTORY_MAX_ROUNDS 的 key） */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  foundation: "基础设定",
  core_theme: "核心主题",
  world_building: "世界观",
  core_conflicts: "核心冲突",
  overall_outline: "整体大纲",
  character_profiles: "人物档案",
  titles: "章节标题",
  chapter: "章节正文",
  arc_outline: "弧线大纲",
  character_status: "人物动态状态",
  character_relations: "人物关系/势力格局",
  foreshadowing: "伏笔台账",
  phase_summary: "阶段固化数据",
};

export function reviewTypeLabel(t: string): string {
  return REVIEW_TYPE_LABELS[t] ?? t;
}
