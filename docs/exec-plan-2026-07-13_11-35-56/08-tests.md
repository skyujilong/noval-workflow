# 08-tests

## Goal
新建 `tests/unit_tests/test_character_profiles_discover.py`，参照 `tests/unit_tests/test_scene_beats.py` 布局，覆盖 5 项契约断言。

## Depends on
- 03-prompts / 04-subgraph-registry / 05-nodes（被测符号已就位）
- 01-contracts-backend（`review_type_to_interrupt_type` 映射）

## Do
1. **先扫参照**：`cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && ls tests/unit_tests/ | grep scene_beats` 确认有无 `test_scene_beats.py`；有则读 5-10 行看夹具风格（state 用 dataclass 直接实例化 or fixture）。
2. 新建 `tests/unit_tests/test_character_profiles_discover.py`，含 5 个测试：
   - `test_prepare_returns_contract`：`_prepare_character_profiles_discover(state)` 返回字典含 `system_context / task_prompt / review_type == "character_profiles_discover"`；`task_prompt` 同时嵌入 `state.character_profiles`（已有档案）与 `state.current_draft`（本章正文）。
   - `test_save_non_empty`：`current_draft = "新档案 markdown"` → `_save_character_profiles_discover(state)` 返回 `{"character_profiles": "新档案 markdown"}`。
   - `test_save_empty_no_clobber`：`current_draft = ""` → 返回 `{}`（不清空原字段）。
   - `test_prompt_placeholder_resolved`：`character_profiles_discover_prompt(state)` 结果不含 `{chapter_num}` / `{existing_profiles}` / `{chapter_draft}` 三个占位符；含 `state.character_profiles` 与 `state.current_draft` 的值。
   - `test_interrupt_mapping`：`from noval_workflow.interrupt_types import review_type_to_interrupt_type, InterruptType; assert review_type_to_interrupt_type("character_profiles_discover") == InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW`。
   - `test_review_prompt_not_phase1_hard_checklist`：`from noval_workflow.subgraph import _REVIEW_PROMPTS; p = _REVIEW_PROMPTS["character_profiles_discover"]; assert "力量体系" in p and "不检查" in p`（正文里同时出现两词才证明"力量体系"被写进"不检查"段，防未来手滑串接 Phase 1 硬清单）。
3. state 构造用 `NovelState()` 直接实例化，赋 `total_chapters_written / character_profiles / current_draft` 三字段即可（无需完整 phase 1 fixture）。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run pytest tests/unit_tests/test_character_profiles_discover.py -v`
   期望：6 项全 pass。

## Notes
- 已完成：新建 `tests/unit_tests/test_character_profiles_discover.py`，6 个测试全 pass（0.33s）。
- 覆盖：prepare 契约 / save 非空 / save 空 no-clobber / prompt 占位符替换 / interrupt 映射 / 审核 prompt 显式「不检查 力量体系」。
