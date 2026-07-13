// 镜像 src/novel_workflow/state.py 的状态字段，供前端类型安全访问 thread state。
// 注意：LangGraph 平台返回的 state 实际在 SDK 的 Thread.values 里。

/** 审稿子状态（subgraph.py ReviewSubState）— 仅前端展示用 */
export interface ReviewHistoryEntry {
  role: "human" | "ai";
  content: string;
}

/**
 * 伏笔台账（state.py `foreshadowing: dict`）。运行时是结构化 dict
 * （形如 `{"pending": [...], "collected": [...]}`），历史遗留数据可能是字符串。
 * 之前前端误标为 string——实际平台返回的是对象；这里按真实形态标注，
 * 兼容老旧字符串格式（后端 _migrate_legacy_foreshadowing 会在读取时迁移）。
 */
export type ForeshadowingLedger = Record<string, unknown> | string;

/** NovelState（state.py）— 平台 thread state 的 values 结构 */
export interface NovelState {
  // Phase -1：灵感脑爆（可选，入口分叉）
  brainstorm_history: ReviewHistoryEntry[];
  brainstorm_summary: string;
  brainstorm_done: boolean;
  from_brainstorm: boolean;

  // Phase 0：用户输入
  novel_name: string;
  genre: string;
  writing_style: string;
  target_audience: string;
  core_tone: string;
  chapter_word_count: string;
  total_word_count: string;

  /** 作品是否含独立【力量体系】——作品级决策（题材默认建议 + 用户可覆盖），非题材属性。
   * 由后端 collect_user_inputs（直接填表路径）/ brainstorm_extract_review（脑爆路径）填充。 */
  has_power_system: boolean;

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
  power_system: string;
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
  foreshadowing: ForeshadowingLedger;
  phase_summary: string;

  // 子图扩展字段（部分子图会用到）
  review_history?: ReviewHistoryEntry[];
  llm_review_max?: number;
  /** 最近一次人工打回的原始意见（ReviewSubState.human_feedback，中断在子图内时可见） */
  human_feedback?: string;
}

/** 空状态，用于初始展示 */
export const EMPTY_NOVEL_STATE: NovelState = {
  brainstorm_history: [],
  brainstorm_summary: "",
  brainstorm_done: false,
  from_brainstorm: false,
  novel_name: "",
  genre: "",
  writing_style: "",
  target_audience: "",
  core_tone: "",
  chapter_word_count: "",
  total_word_count: "",
  has_power_system: false,
  system_context: "",
  task_prompt: "",
  current_draft: "",
  review_feedback: "",
  approved: false,
  review_type: "foundation",
  llm_review_count: 0,
  core_theme: "",
  world_building: "",
  power_system: "",
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
  foreshadowing: {},
  phase_summary: "",
};

/** review_type → 中文标签（来自 subgraph.py _REVIEW_PROMPTS / _HISTORY_MAX_ROUNDS 的 key） */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  foundation: "基础设定",
  core_theme: "核心主题",
  world_building: "世界观",
  power_system: "力量体系",
  core_conflicts: "核心冲突",
  overall_outline: "整体大纲",
  character_profiles: "人物档案",
  titles: "章节标题",
  chapter: "章节正文",
  arc_outline: "弧线大纲",
  chapter_plan: "章节规划(远端锚点)",
  character_status: "人物动态状态",
  character_relations: "人物关系/势力格局",
  foreshadowing: "伏笔台账",
  phase_summary: "阶段固化数据",
  scene_beats: "章节 scene beats",
  character_profiles_discover: "角色档案发现",
};

export function reviewTypeLabel(t: string): string {
  return REVIEW_TYPE_LABELS[t] ?? t;
}

/** 自进化闭环生效的审核环节：会重复生成的环节消费 evolved_directives，
 *  故只在它们打回时落库 REJECT 记录、并在中断处显示进化入口。
 *  scene_beats 是章前节拍表，打回意见（打脸/钩位/节奏塌）与 chapter/arc 同源，
 *  共用 evolved_directives 字段回流到下一章 beats 与后续正文创作。 */
export const EVOLVABLE_REVIEW_TYPES = new Set(["chapter", "arc_outline", "scene_beats"]);
