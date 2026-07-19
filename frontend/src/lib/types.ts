// 镜像 src/novel_workflow/state.py 的状态字段，供前端类型安全访问 thread state。
// 注意：LangGraph 平台返回的 state 实际在 SDK 的 Thread.values 里。

/** 审稿子状态（subgraph.py ReviewSubState）— 仅前端展示用 */
export interface ReviewHistoryEntry {
  role: "human" | "ai";
  content: string;
}

/**
 * 伏笔台账（state.py `foreshadowing: dict`）。运行时是结构化 dict
 * （形如 `{"pending": [...], "collected": [...]}`）。string 分支仅为兜底历史遗留的
 * 纯文本台账（编辑器走 legacy textarea），新流程一律产出结构化 dict。
 */
export type ForeshadowingLedger = Record<string, unknown> | string;

/** chapter_plan 单条(镜像 state.py::ChapterPlanItem)。 */
export interface ChapterPlanItem {
  chapter: number;
  purpose: string;
  key_turn: string;
  ending_hook: string;
  intensity?: string;
}

/** 分卷条目（镜像 state.py::Volume）。横向大结构中间层——overall_outline 之下、chapter_plan 之上。
 *
 * 滚动生成卷 + 前瞻队列语义（与后端一致）：
 *  - chapter_start 是本卷**起始章号**（1-based，由后端 save_volumes 权威锁定）
 *  - planned_end 是本卷**末章号**（绝对章号，权威边界）；卷内窗口 = [chapter_start, planned_end]，
 *    本卷章数 = planned_end - chapter_start + 1
 *  - actual_end：滚动到下一卷时上一卷收口写入（= planned_end）；进行中卷为 null
 *  - status: planning(前瞻草稿·未锁章号) | in_progress(进行中) | closed(已收卷)
 *  - **前瞻草稿卷**：status=planning 且 chapter_start=planned_end=0（未锁章号）——只有方向骨架
 *    title/summary/setup_for_next，轮到激活时后端才权威锁章号转正。判定「已激活」统一用 planned_end>0。
 */
export interface Volume {
  index: number;
  title: string;
  summary: string;
  setup_for_next: string;
  // chapter_start：起始章号；前瞻草稿卷为 0（未锁）。
  chapter_start: number;
  // planned_end：本卷规划末章号（绝对章号，权威边界）；前瞻草稿卷为 0（未锁，判「已激活」用 >0）。
  planned_end: number;
  // chapters：本卷章数——仅 volumes review 草稿的**激活卷**可编辑字段；落库卷用 planned_end 导出，无此字段。
  chapters?: number;
  actual_end: number | null;
  status: "planning" | "in_progress" | "closed";
}

/** 统一实体卡(镜像 state.py 的 EntityCard 判别联合)。
 * 前端用「扁平并集接口」镜像后端 CharacterCard/ItemCard/SimpleEntityCard——type 不适用的字段为
 * undefined，渲染时按 type 分支取字段。 */
export interface EntityCard {
  name: string;
  type: string; // 人物 / 物品 / 装备 / 势力 / 地点
  aliases?: string[];
  summary?: string;
  first_appear_chapter?: number;
  // 人物段(CharacterCard)
  role?: string; // 角色定位：主角/主要配角/功能性反派/根源反派/感情线角色/次要角色
  appearance?: string;
  speech_style?: string;
  personality?: string;
  abilities?: string;
  hidden_persona?: string; // 深层隐藏人设(canon·深层视图)
  arc_trajectory?: string; // 全书成长弧光(canon·深层视图)
  ability_contract?: string; // 能力底牌契约(canon·深层视图)
  motivation?: string; // 动态
  current_state?: string; // 当前处境(动态，吸收原 character_status)
  relations?: string; // 动态
  // 物品/装备段(ItemCard)
  owner?: string;
  effect?: string;
  status?: string;
  rank?: string;
  // 势力/地点段(SimpleEntityCard)
  standing?: string; // 势力强弱/格局(动态，吸收原 character_relations 势力部分)
}

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
  // 人物档案真源已并入 entity_cards（CharacterCard），不再有独立的 character_profiles 散文字段

  // Phase 2：章节写作追踪
  current_batch_titles: string[];
  all_chapter_titles: string[];
  all_chapter_summaries: string[];
  current_chapter_index: number;
  total_chapters_written: number;
  continue_writing: boolean;

  // Phase 2.5：弧线与动态状态库
  // 人物动态状态/关系已并入 entity_cards（CharacterCard.current_state/relations、势力 standing）
  current_arc_outline: string;
  foreshadowing: ForeshadowingLedger;
  phase_summary: string;

  // Phase 2.5：章节规划(chapter_plan，以卷为规划单元的中景大纲)
  chapter_plan: ChapterPlanItem[];
  chapter_plan_planned_upto: number;

  // Phase 1.5：分卷规划（Volumes，横向大结构中间层）
  // 由 prepare_volumes 从 overall_outline 抽取 → review_volumes 用户编辑 → save_volumes 落库。
  // 空数组代表未启用分卷（老小说向后兼容）。
  volumes: Volume[];

  // Phase 2.7：统一实体卡库(EntityCard 人物/物品/装备/势力/地点)
  entity_cards: EntityCard[];

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
  current_batch_titles: [],
  all_chapter_titles: [],
  all_chapter_summaries: [],
  current_chapter_index: 0,
  total_chapters_written: 0,
  continue_writing: true,
  current_arc_outline: "",
  foreshadowing: {},
  phase_summary: "",
  chapter_plan: [],
  chapter_plan_planned_upto: 0,
  volumes: [],
  entity_cards: [],
};

/** review_type → 中文标签（来自 subgraph.py _REVIEW_PROMPTS / _HISTORY_MAX_ROUNDS 的 key） */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  foundation: "基础设定",
  core_theme: "核心主题",
  world_building: "世界观",
  power_system: "力量体系",
  core_conflicts: "核心冲突",
  overall_outline: "整体大纲",
  character_cards: "人物档案（结构化卡司）",
  titles: "章节标题",
  chapter: "章节正文",
  arc_outline: "弧线大纲",
  chapter_plan: "章节规划(远端锚点)",
  volumes: "分卷规划",
  volume_cast: "本卷花名册",
  foreshadowing: "伏笔台账",
  phase_summary: "阶段固化数据",
  scene_beats: "章节 scene beats",
  entity_cards: "登场实体卡",
  entity_discover: "实体发现/更新",
};

export function reviewTypeLabel(t: string): string {
  return REVIEW_TYPE_LABELS[t] ?? t;
}

/** 自进化闭环生效的审核环节：会重复生成的环节消费 evolved_directives，
 *  故只在它们打回时落库 REJECT 记录、并在中断处显示进化入口。
 *  scene_beats 是章前节拍表，打回意见（打脸/钩位/节奏塌）与 chapter/arc 同源，
 *  共用 evolved_directives 字段回流到下一章 beats 与后续正文创作。 */
export const EVOLVABLE_REVIEW_TYPES = new Set(["chapter", "arc_outline", "scene_beats"]);
