# 05-nodes

## Goal
新建 `nodes/character_profiles_discover.py`：`_prepare` + `_save` 两个闭包，签名与 `nodes/scene_beats.py` 对齐。

## Depends on
- 03-prompts（`character_profiles_discover_prompt` / `build_foundation_context` 可用）

## Do
1. 新建 `src/novel_workflow/nodes/character_profiles_discover.py`。
2. 导入：
   ```python
   from __future__ import annotations
   import logging
   from noval_workflow.context import build_foundation_context
   from noval_workflow.prompts import character_profiles_discover_prompt
   _logger = logging.getLogger(__name__)
   ```
3. `def _prepare_character_profiles_discover(state) -> dict`：
   - docstring 说明：system_context 用完整基础设定（含世界观/力量体系/大纲/已有人物档案）；task_prompt 用 discover 组装函数（读 current_draft 本章正文 + character_profiles 已有档案 + total_chapters_written 本章号）。
   - 返回 `{"system_context": build_foundation_context(state), "task_prompt": character_profiles_discover_prompt(state), "review_type": "character_profiles_discover"}`。
4. `def _save_character_profiles_discover(state) -> dict`：
   - docstring 说明：LLM 全量输出合流后档案，直接覆盖写回；空 draft 时 warn 并不改动（不 clobber）。
   - 空兜底：`if not state.current_draft: _logger.warning("character_profiles_discover current_draft 为空，未写入 character_profiles"); return {}`
   - 否则：`_logger.info("character_profiles_discover 落地：第 %d 章，档案长度 %d 字符", state.total_chapters_written, len(state.current_draft))` + `return {"character_profiles": state.current_draft}`

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run python -c "
from noval_workflow.nodes.character_profiles_discover import _prepare_character_profiles_discover, _save_character_profiles_discover
from noval_workflow.state import NovelState
s = NovelState()
s.total_chapters_written = 3
s.character_profiles = '主角：李云'
s.current_draft = '本章正文……'
r = _prepare_character_profiles_discover(s)
assert r['review_type'] == 'character_profiles_discover'
assert '{chapter_num}' not in r['task_prompt']  # 已 format
assert '本章正文' in r['task_prompt']
r = _save_character_profiles_discover(s)
assert r == {'character_profiles': '本章正文……'}
s.current_draft = ''
r = _save_character_profiles_discover(s)
assert r == {}
print('OK')
"`

## Notes
- 已完成：新建 `src/novel_workflow/nodes/character_profiles_discover.py`。
- Verify 通过：prepare 返回三字段（system_context/task_prompt/review_type）+ task_prompt 已 format（无 `{chapter_num}` 占位符残留）+ save 非空返回 `{'character_profiles': draft}`、空返回 `{}`（不 clobber）。
