# 04-prepare-chapter-arc

## Goal
迁移 chapter/titles/arc/chapter_plan/scene_beats/volumes/volume_cast/entity_cards/entity_discover 这些 prepare + generate_summary 独立 LLM 点到三层结构。含 evolved_directives 三桶、{prev} 移 L2、arc_outline deep_character_view=True、entity_discover 身份修复。

## Depends on
- 01(render_user/build_prepare_fields)、02(schema)、03(foundation 模式 + 验收脚本框架) 完成

## Do
1. chapter.py prepare_titles：L1=system_identity/"生成下N章标题"；L2=build_foundation_context(include_identity=False)；L3=pack.titles_prompt(...)（titles_prompt 不含 identity，无需删）
2. chapter.py prepare_chapter：L1=system_identity/"撰写章节正文"；L2=build_foundation_context(include_identity=False)；L3=pack.chapter_prompt(...) + cards_section（chapter_prompt 开头 identity 已在 03 删；evolved_directives_chapter 桶在 chapter_prompt 末尾，不动）
3. chapter.py generate_summary：独立 LLM 点。system=build_system(system_identity,"章节摘要")；L2=build_foundation_context(include_identity=False)；user=render_user(L2, SUMMARY_PROMPT.format(...))。不再复用 state.system_context（字段已删）
4. arc.py prepare_arc_outline：L1=system_identity/"规划本批弧线大纲"；L2=build_foundation_context(include_identity=False, deep_character_view=True)（P2风险点：deep 应 True）；L3=pack.arc_outline_prompt(state)（evolved_directives_arc_outline 桶在末尾，不动）
5. chapter_plan.py prepare_chapter_plan：L1=system_identity/"中景章节规划"；L2=build_foundation_context(include_identity=False)；L3=pack.chapter_plan_prompt(...)。注意 state_snapshot（伏笔/阶段固化）双注：prompt 内部 format_chapter_plan_state_snapshot 又注入--确认是否在 L2 已有，若双注则 task 不再重复（评估后定，可能保留因是规划特异快照）
6. scene_beats.py _prepare_scene_beats：L1=system_identity/"设计章内 scene beats"；L2=build_foundation_context(include_identity=False)；L3=scene_beats_prompt(state, build_chapter_context(state))（evolved_directives_scene_beats 桶在末尾，不动）
7. volumes.py prepare_volumes：L1=system_identity/"规划分卷"；L2=build_foundation_context(include_identity=False)（含 overall_outline，task 不再传 overall_outline--volumes_prompt 首参是 overall_outline，需评估：overall_outline 在 L2 已有，prompt 内部还作参数拼，可能双注。**决策：overall_outline 仍作参数传给 prompt（prompt 内用它组织任务），但确认 build_foundation_context 的 overall_outline 段与 prompt 内的不重复语义**）
8. volume_cast.py prepare_volume_cast：L1=system_identity/"规划卷阵容"；L2=build_foundation_context(include_identity=False)；L3=volume_cast_prompt(state, active_volume)
9. entity_cards.py _prepare_entity_cards：L1=system_identity/"识别+建新实体卡"；L2=build_foundation_context(include_identity=False)；L3=entity_cards_prompt(state)
10. entity_cards.py _prepare_entity_discover：P0风险点身份缺失。L1=system_identity/"发现新实体+更新动态"（**给身份！**非 snapshot 但原 include_identity=False 导致裸设定）；L2=build_foundation_context(include_identity=False, exclude_snapshots=True)；L3=entity_discover_prompt(state, build_chapter_context(state))
11. 验收脚本 run_prepare_checks 扩展：加这 9 个 prepare 的检查（与 foundation 同模式：三字段/无双注/资料不在L1/硬契约在L1/资料在L2）

## Verify
1. ruff format+check 全部改动文件
2. python scripts/verify_prompt_arch.py：core_theme 8 + foundation 35 + 新增 chapter 类 prepare 检查全 PASS
3. 重点人工核对：prepare_chapter 的 evolved_directives 在 L3 末尾、generate_summary 不再读 system_context、entity_discover 有身份
4. 不跑全量 pytest（subgraph 06 未改）

## Notes
- 执行结果：✅ 完成
- 改动文件（7 个 prepare + 1 验收脚本）：
  - arc.py：prepare_arc_outline（deep_character_view=True 修复 P2 风险点）
  - chapter_plan.py：prepare_chapter_plan
  - scene_beats.py：_prepare_scene_beats（前文 chapter_context 移 L2）
  - volumes.py：prepare_volumes
  - volume_cast.py：prepare_volume_cast（题材中性 prompt，L1 给 system_identity）
  - entity_cards.py：_prepare_entity_cards + _prepare_entity_discover（P0 修复：entity_discover 身份缺失->给 system_identity）
  - chapter.py：prepare_titles / prepare_chapter（chapter_prompt 开头 identity 已在 03 删）+ generate_summary（独立 LLM 点改三层，不再读 system_context）
- 验收脚本扩展：mock state 加 volumes/current_batch_titles/current_arc_outline；run_prepare_checks 加 9 个 chapter 类 prepare
- 验证：ruff 全过 / 验收脚本 79 项全 PASS（core_theme 8 + foundation 35 + chapter类 36 = 79），0 FAIL
- 顺手修既有 E741（chapter.py 的 l 变量 -> line）
- 关键确认：16 个 prepare 全部身份无双注、资料不在 L1（在 L2）、硬契约在 L1、三字段齐全
- evolved_directives 三桶（chapter/arc_outline/scene_beats）仍在 prompt 方法末尾注入 L3，不动
- 预期红：subgraph/generate_summary 外的独立点 + edit 子图引用 system_context 未改（05/06/07/08 修）

