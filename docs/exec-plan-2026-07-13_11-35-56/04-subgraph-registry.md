# 04-subgraph-registry

## Goal
在 `subgraph.py` 里注册新 review_type：imports 拉入 `CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT`，`_HISTORY_MAX_ROUNDS` / `_REGEN_OUTPUT_HINTS` / `_REVIEW_PROMPTS` 三张表各加一条。

## Depends on
- 03-prompts（prompt 常量在 `noval_workflow.prompts` 命名空间可见）
- 01-contracts-backend（review_type 字符串已在 InterruptType 映射表登记）

## Do
1. 打开 `src/novel_workflow/subgraph.py`。
2. 在第 11-29 行 imports 里的 `SCENE_BEATS_REVIEW_PROMPT,` 之后追加：
   ```
   CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT,
   ```
3. 在 `_HISTORY_MAX_ROUNDS`（第 40-55 行）里 `"scene_beats": 3,` 之后追加：
   ```
   "character_profiles_discover": 3,
   ```
4. 在 `_REGEN_OUTPUT_HINTS`（第 77-113 行的 dict）里 `"scene_beats": (...)` 之后追加一条覆盖式 hint。默认散文提示会误导 LLM 把 discover 输出当章节正文；显式说明"这是【人物档案 markdown】，必须保留原有条目原样"：
   ```
   "character_profiles_discover": (
       "直接输出修改后的完整【人物档案 markdown】——**不是章节正文**，"
       "不得描述你做了哪些修改、不得使用「修改」「替换」「调整」等元叙述语言。"
       "必须保留输入档案中所有原有角色条目原样，只允许追加新角色或在原条目末尾追加「【本章新增】…」补充段。"
   ),
   ```
5. 在 `_REVIEW_PROMPTS`（第 116-131 行）里 `"scene_beats": SCENE_BEATS_REVIEW_PROMPT,` 之后追加：
   ```
   "character_profiles_discover": CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT,
   ```
6. `_EVOLVABLE_REVIEW_TYPES`（第 35 行）**不改**（决策 8）。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run python -c "from noval_workflow.subgraph import _REVIEW_PROMPTS, _HISTORY_MAX_ROUNDS, _REGEN_OUTPUT_HINTS, _EVOLVABLE_REVIEW_TYPES; assert 'character_profiles_discover' in _REVIEW_PROMPTS; assert _HISTORY_MAX_ROUNDS.get('character_profiles_discover') == 3; assert '人物档案 markdown' in _REGEN_OUTPUT_HINTS['character_profiles_discover']; assert 'character_profiles_discover' not in _EVOLVABLE_REVIEW_TYPES; print('OK')"`

## Notes
- 已完成：imports 追加 `CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT`，三张表各加一条。
- Verify 通过：`_REVIEW_PROMPTS['character_profiles_discover']` 存在；`_HISTORY_MAX_ROUNDS==3`；`_REGEN_OUTPUT_HINTS` 含「人物档案 markdown」；`_EVOLVABLE_REVIEW_TYPES` 未污染。
