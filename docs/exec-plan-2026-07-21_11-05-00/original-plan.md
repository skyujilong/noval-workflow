# Prompt 三层架构全迁执行计划

## 目标
把项目 prompt 从"system_context(str) 塞全部资料+身份 + task_prompt(str) 任务"的双字符串范式，
一次全迁为三层结构：L1 system(身份+硬契约+任务契约+优先级约定) / L2 context(参考资料) / L3 task(本次指令+输出格式+evolved)。
零兼容层、无混合状态。generate/llm_self_review 只走一套 render。

## 已定决策（用户拍板）
1. 一次全迁 16+ 个 prepare，不留兼容层（用户明确"不要历史包袱"）。
2. 拆分在 **prepare 层**做：prompt 方法保持返回单字符串 task，prepare 负责组 L1/L2/L3。
   prompt 方法唯一改动：删开头的 system_identity 双注（overall_outline/character_cards/chapter_prompt 三处）。
3. 锚点（arc本章段/beats/plan锚点/卷位置卡）暂留 L3（与任务规则同源、任务特异）。
4. 不兼容老 checkpoint。
5. 双防线：system 优先级约定（位置词）+ task 末尾 evolved 边界声明。硬契约 HARD_CONTRACTS 单一真源。
6. 验收脚本扩展覆盖每个 prepare，确保迁移无丢资料。

## 三层定义与映射
- L1 system = build_system(identity, task_contract)：身份 + 4 硬契约 + 任务契约 + 优先级约定
- L2 context = 设定/台账（build_foundation_context 去 identity）+ 前文（build_chapter_context）+ snapshot 的 prev/chapter_context
- L3 task = prompt 方法返回的指令串（删 system_identity）+ cards_section 等末尾追加 + evolved_directives

## state schema 变更
ReviewSubState / NovelState 的桥接字段：
- 删 `system_context: str`
- 加 `system_prompt: str`（L1，原 system_context 改名+语义收窄为纯 L1）
- 加 `context_prompt: str`（L2，参考资料）
- 保留 `task_prompt: str`（L3，纯任务，不再含 L2 资料）
默认空串，无兼容层。

## prepare 层统一模式（核心 helper）
prepare 节点统一产出 dict：`{system_prompt, context_prompt, task_prompt, review_type, **reset_review_fields()}`。
设计 helper 函数封装通用组装：
- `build_review_prompts(state, *, review_type, task_contract, context_sections, task, identity=None, snapshot=False)`
  返回三个字段。identity 默认 flavor.system_identity；snapshot 类 identity 用"数据维护员/审核员"内联。
- L2 组装：多数 prepare 调 build_foundation_context(state, include_identity=False)；snapshot 类 exclude_snapshots=True；
  chapter/titles/scene_beats 等额外加 build_chapter_context；ledger 的 prev 由 prepare 注入 L2（不进 task）。

## generate / llm_self_review 改造（subgraph.py）
- generate 非 snapshot 首轮：messages = [SystemMessage(system_prompt), HumanMessage(render_user(context_prompt, task_prompt))]
- generate snapshot 首轮：system = build_system("数据维护员身份", contract) + context_prompt；或沿用内联拼装改走 render
- generate 重放分支：历史轮次无 L2 可接受，最新轮用 render_user(context_prompt, regen_instruction)
- llm_self_review 非 snapshot：system=SystemMessage(system_prompt) + user=render_user(context_prompt, review_prompt)（解决自审丢资料！）
- llm_self_review snapshot：system=审核员身份+context_prompt + review_prompt
- evolved_directives 注入：chapter/arc_outline/scene_beats 三桶，仍由 prompt 方法末尾注入（不动）
- 无条件分支：generate 只一套 render 逻辑，无 context_prompt 空回退

## generate_summary 改造（chapter.py:157）
独立 LLM 调用点：system=build_system(身份,"章节摘要") + context=L2设定 + user=SUMMARY_PROMPT。
不再复用前序残留 system_context。

## snapshot 类（foreshadowing/phase_summary/initial_status）
- identity 用内联"数据维护员"（generate 现有逻辑搬进 prepare 的 L1）
- exclude_snapshots=True（台账更新类不重复注入快照到 L2）
- prev（上次台账）从 ledger.prompt 移出，由 prepare 注入 L2（解 {prev} 与任务交织）
- initial_status: deep_character_view=True

## edit 子图
- chapter_edit_subgraph 的 _prepare_foreshadowing/_prepare_phase：走 snapshot 模式
- chapter_plan_edit_subgraph 的 cp_entry 三处 LLM：各自定 context_prompt（不再共用一份）
- edit_step_subgraph 的 step_prepare 闭包：透传新三字段

## 其他独立 LLM 调用点
- brainstorm.py 各 SystemMessage：适配 build_system（身份+硬契约），history 走 L2/L3 语义
- consistency.py：CONSISTENCY_AUDIT/REVISE 的硬约束与 HARD_CONTRACTS 归一（单一真源）
- entity_cards_prune_subgraph / foreshadow_prune_subgraph：身份进 L1，判定数据走 L2

## 风险点（调研 P0-P3，迁移时逐一处理）
P0: entity_discover 身份缺失（非 snapshot 又 include_identity=False）-> 给身份
P1: 5 处双注（身份/伏笔/设定/overall_outline/人物档案）-> prepare 层去重
P2: cp_entry 三处共用 system_context -> 各自定 L2；arc_outline deep_character_view 应 True；generate_summary 精简 L2
P3: brainstorm 动态 system；consistency 硬约束归一；prune 子图是否走 context 管线

## 验收机制（核心交付）
扩展 scripts/verify_prompt_arch.py：
- 为每个 prepare 节点构造 mock state，跑新路径，打印三层，自动检查
- 通用检查：身份只在 L1（无双注）、资料在 L2 不在 system、HARD_CONTRACTS 在 L1、render 结构 1+1
- 特化检查：snapshot 类有"数据维护员"身份、chapter 含 evolved_directives、ledger 的 prev 在 L2 不在 task
- 退出码反映全部检查

## 测试
- 全量 pytest 零回归（除既有 test_perf_log_sections/test_character_promote fail）
- 新增 test_prompt_render 扩展（render_user / build_system snapshot 模式）
- llm.py _PerfLogHandler 的 section 解析适配新结构（system 瘦了，资料在 user）

## 步骤索引（build order）
01-render-user-helper       # render.py 加 render_user(context, task)；build_system 支持 snapshot 身份
02-state-schema             # ReviewSubState/NovelState 三字段，删 system_context
03-prepare-foundation       # 7 个 foundation prepare
04-prepare-chapter-arc      # chapter/titles/arc/scene_beats/volumes/volume_cast/chapter_plan prepare + generate_summary
05-prepare-snapshot         # foreshadowing/phase/initial_status snapshot 类 + edit 子图
06-generate-self-review     # subgraph.generate/llm_self_review 走 render，解决自审丢资料
07-edit-subgraphs           # chapter_plan_edit cp_entry 三处 + edit_step 闭包
08-independent-llm          # brainstorm/consistency/prune 独立 LLM 调用点
09-verify-expand            # 验收脚本扩展覆盖全部 prepare
10-test-final               # 全量测试 + llm.py section 解析适配 + 最终验收
