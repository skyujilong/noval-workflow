# 03-prompts

## Goal
新建 `prompts/character_profiles_discover.py`：生成 prompt + 审核 prompt + 组装函数；在 `prompts/__init__.py` 里 re-export。

## Depends on
- 无（内容不依赖其他新代码）

## Do
1. 新建 `src/novel_workflow/prompts/character_profiles_discover.py`，导出三个符号：
   - `CHARACTER_PROFILES_DISCOVER_PROMPT: str`（含 `{chapter_num}` / `{existing_profiles}` / `{chapter_draft}` 占位符）
   - `CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT: str`（含 `{draft}` 占位符）
   - `def character_profiles_discover_prompt(state) -> str`：读 `state.current_draft`（本章正文）+ `state.character_profiles`（已有档案）+ `state.total_chapters_written + 1`（本章号），return `.format(...)` 结果。

   生成 prompt 硬约束（在正文里体现）：
   - 任务定位：本章正文已完成，识别新角色 / 补充已知角色新信息，输出**合流后的完整 markdown**。
   - 保真硬约束：保留【已有人物档案】所有原有条目**原样**，禁止裁剪 / 总结 / 重写。只在末尾追加新角色，或在原条目末尾追加"【第 {N} 章新增】…"补充段。
   - 反幻觉：不得虚构本章未提及的角色；不得改写已定角色的性格 / 立场 / 能力上限。
   - 宽松形式：新次要角色允许 3-5 行简介，不要求力量体系归属 / 双层人设 / 成长天花板。
   - 空发现允许：若本章无新角色且已知角色无新暴露，直接原样吐回 existing_profiles。
   - 输出契约：整块 markdown（**不是章节正文**），不带 code fence，不带解释文字。

   审核 prompt 硬约束：
   - 显式声明"**不检查**卡司配额 / 双层人设 / 能力底牌契约 / 力量体系归属"（防串接 `CHARACTER_PROFILES_REVIEW_PROMPT`）。
   - 只查三点：① 保留原档案全部条目；② 新增角色确在本章正文中出现；③ 新增段插入位置合理。
   - 通过阈值：三点满足即输出 `无问题`（对齐 `subgraph.PASS_SIGNALS`）。

2. 修改 `src/novel_workflow/prompts/__init__.py`：
   - 在第 58 行 `from noval_workflow.prompts.scene_beats import (...)` 段之后追加：
     ```python
     from noval_workflow.prompts.character_profiles_discover import (
         CHARACTER_PROFILES_DISCOVER_PROMPT,
         CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT,
         character_profiles_discover_prompt,
     )
     ```
   - 在 `__all__`（第 128-134 行 scene beats 段落之后）追加三个字符串。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && python -c "from noval_workflow.prompts import CHARACTER_PROFILES_DISCOVER_PROMPT, CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT, character_profiles_discover_prompt; assert '{chapter_num}' in CHARACTER_PROFILES_DISCOVER_PROMPT and '{existing_profiles}' in CHARACTER_PROFILES_DISCOVER_PROMPT and '{chapter_draft}' in CHARACTER_PROFILES_DISCOVER_PROMPT; assert '{draft}' in CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT; assert '力量体系' not in CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT and '卡司配额' not in CHARACTER_PROFILES_DISCOVER_REVIEW_PROMPT; print('OK')"`

## Notes
- Changed: 新建 `src/novel_workflow/prompts/character_profiles_discover.py`；`prompts/__init__.py` +3 re-export
- **章号对齐修正**：`save_chapter`（`nodes/chapter.py:127-129`）已经把 `total_chapters_written` 自增到本章号，所以组装函数用 `state.total_chapters_written`（不 +1），与 mini-plan 里"+1"表述**不一致**——采取代码实测语义，因为发现流程运行在 save_chapter 之后。已在函数 docstring 里注明。
- Verify: uv run python 断言 OK（占位符齐全 / 审核 prompt 显式排除 Phase 1 硬清单 / 空态兜底）
