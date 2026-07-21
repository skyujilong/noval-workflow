# Resume Guide

## 当前进度
- 执行目录: docs/exec-plan-2026-07-21_11-05-00/
- 已完成: 01 ~ 10 全部完成
- 状态: 全绿收尾（verify 脚本 99 PASS/0 FAIL；全量单测 287 passed/0 failed；lint 干净）

## Resume 命令
计划已全部完成，无需 resume。如需复盘：original-plan.md -> split-audit.md -> checkpoint.json -> step.json。

## 已完成摘要
- 01: render.py 加 render_user + build_prepare_fields + SNAPSHOT_IDENTITY 常量；render() 重构调 render_user
- 02: state.py ReviewSubState/NovelState 删 system_context，加 system_prompt(L1)/context_prompt(L2)/task_prompt(L3)
- 03: foundation.py 7 prepare 全用 build_prepare_fields；base.py 删 3 处 identity 双注；验收脚本加 7 prepare 批量检查
- 04: chapter 类 prepare（titles/chapter/arc_outline/chapter_plan/scene_beats/volumes/volume_cast/entity_cards/entity_discover）+ arc.py deep_character_view + chapter.generate_summary 三层化
- 05: chapter_edit_subgraph schema 三字段；_prepare_foreshadowing/_prepare_phase 用 SNAPSHOT_IDENTITY_MAINTAINER
- 06: subgraph.generate/llm_self_review 统一 [SystemMessage(L1), HumanMessage(render_user(L2,L3))]；自审走 render_user 解决丢资料；render_user import 提顶
- 07: chapter_plan_edit_subgraph schema 三字段 + 三处独立 LLM 就地 build_system+render_user；edit_step_subgraph 统一
- 08: consistency/entity_cards_prune/foreshadow_prune 独立 LLM 点统一 build_system
- 09: 验收脚本加 generate/自审拼装检查（mock LLM 录制 messages）+ 独立 LLM 点硬契约检查；99 PASS/0 FAIL
- 10: 全量单测 287 passed/0 failed；llm.py _PerfLogHandler 适配新结构（设定移到 user，sections 改从首条 human 解析，函数 rename _parse_system_sections->_parse_context_sections）；修 3 处既有 perf-log 测试 + 加 1 处 handler 行为测试

## 关键约束
- 零兼容层、拆分在 prepare 层、generate 只一套 render、双防线、验收脚本核心交付
