# 06-subgraph-wire

## Goal
新建 `character_profiles_discover_subgraph.py`：定义 SubState（空子类，形态对称）+ 调用 `make_edit_step_subgraph` 工厂产出 `character_profiles_discover_step` 顶级对象。

## Depends on
- 01-contracts-backend（InterruptType.CHARACTER_PROFILES_DISCOVER_* 三个枚举可用）
- 05-nodes（`_prepare_character_profiles_discover` / `_save_character_profiles_discover` 可导入）
- 04-subgraph-registry（review_type 已在 `_REVIEW_PROMPTS` 登记）

## Do
1. 新建 `src/novel_workflow/character_profiles_discover_subgraph.py`。
2. 内容对齐 `scene_beats_subgraph.py`：
   - 模块 docstring：说明本子图插在 generate_summary 之后、chapter_edit_subgraph 之前；每章都跑；空回车即整章跳过；写回单字段 `character_profiles: str`（决策 1）。
   - `@dataclass class CharacterProfilesDiscoverSubState(EditStepSubState): pass`（**不加字段**，`character_profiles` 已在父类镜像；显式空子类保持与 `SceneBeatsSubState` 对称形态）。
   - 模块级 `_ENTRY_HINT`（换行 + 提示语，格式对齐 `scene_beats_subgraph.py:39`）。
   - 顶级导出：
     ```python
     character_profiles_discover_step = make_edit_step_subgraph(
         entry_prompt="是否根据本章正文发现新角色 / 补充已知角色档案？" + _ENTRY_HINT,
         prepare_fn=_prepare_character_profiles_discover,
         save_fn=_save_character_profiles_discover,
         entry_gate_type=InterruptType.CHARACTER_PROFILES_DISCOVER_ENTRY_GATE,
         direction_type=InterruptType.CHARACTER_PROFILES_DISCOVER_DIRECTION_INPUT,
         enable_llm_review=True,
         llm_review_max=2,
         ask_direction=False,
         enable_prune=False,
         state_cls=CharacterProfilesDiscoverSubState,
     )
     ```

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run python -c "from noval_workflow.character_profiles_discover_subgraph import character_profiles_discover_step, CharacterProfilesDiscoverSubState; from noval_workflow.edit_step_subgraph import EditStepSubState; assert issubclass(CharacterProfilesDiscoverSubState, EditStepSubState); assert callable(character_profiles_discover_step.invoke); print('OK')"`

## Notes
- 已完成：新建 `src/novel_workflow/character_profiles_discover_subgraph.py`，空子类 + 工厂调用完全对齐 scene_beats_subgraph.py。
- Verify 通过：`CharacterProfilesDiscoverSubState ⊂ EditStepSubState`；`character_profiles_discover_step.invoke` 可调用。
