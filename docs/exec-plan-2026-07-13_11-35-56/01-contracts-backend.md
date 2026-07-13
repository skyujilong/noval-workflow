# 01-contracts-backend

## Goal
在 `interrupt_types.py` 里新增 3 个 InterruptType 枚举（entry_gate / direction_input / review）并登记 review_type → InterruptType 映射。这是前后端契约的后端一半，前端 step 02 会镜像。

## Depends on
- 无（契约层，最先落地）

## Do
1. 打开 `src/novel_workflow/interrupt_types.py`。
2. 在第 70 行 `SCENE_BEATS_REVIEW = "scene_beats_review"` 之后追加分节 + 3 个枚举：
   ```
   # 章级角色档案发现（每章正文完成后自动，可跳步骤；插在 generate_summary 之后、chapter_edit_subgraph 之前）
   CHARACTER_PROFILES_DISCOVER_ENTRY_GATE = "character_profiles_discover_entry_gate"
   CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT = "character_profiles_discover_direction_input"
   CHARACTER_PROFILES_DISCOVER_REVIEW = "character_profiles_discover_review"
   ```
3. 在 `_REVIEW_TYPE_TO_INTERRUPT_TYPE` 字典（第 104-114 行）内 `"scene_beats": InterruptType.SCENE_BEATS_REVIEW,` 之后追加：
   ```
   "character_profiles_discover": InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW,
   ```
4. 更新第 111-113 行的旁注注释，把新的 review_type 从"共用通用审核表单"名单里显式排除（如果注释列了名单，加一句"character_profiles_discover 走专属 InterruptType"）。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && python -c "from noval_workflow.interrupt_types import InterruptType, review_type_to_interrupt_type; assert InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW.value == 'character_profiles_discover_review'; assert review_type_to_interrupt_type('character_profiles_discover') == InterruptType.CHARACTER_PROFILES_DISCOVER_REVIEW; print('OK')"`

## Notes
- Changed: `src/novel_workflow/interrupt_types.py`
  - +3 枚举成员（ENTRY_GATE / DIRECTION_INPUT / REVIEW），插在 SCENE_BEATS_REVIEW 之后
  - +1 条 `_REVIEW_TYPE_TO_INTERRUPT_TYPE` 映射，附一行注释解释"专属 InterruptType"的用意
- Verify: `uv run python -c "..."` OK（3 值断言 + 映射 + REVIEW_GENERIC 兜底路径）
