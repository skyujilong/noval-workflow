# 02-state-schema

## Goal
ReviewSubState / NovelState 桥接字段从 `system_context: str` 改为三字段：`system_prompt`(L1) / `context_prompt`(L2) / `task_prompt`(L3)。删 system_context，零兼容层。

## Depends on
- 01 完成（render_user 就绪）

## Do
1. state.py ReviewSubState：删 `system_context: str`，加 `system_prompt: str = ""` + `context_prompt: str = ""`。task_prompt 保留。更新字段注释（L1/L2/L3 语义）。
2. state.py NovelState 桥接字段：同步改（NovelState 也有 system_context 桥接字段，见 state.py:295）。
3. reset_review_fields()（state.py:412）：当前清 current_draft/review_feedback/approved/review_history/llm_review_count/llm_review_max。确认是否需加清 system_prompt/context_prompt/task_prompt？**否**--这些是 prepare 每次重写的，reset 不应清（reset 只清 review 循环态）。保持不变。
4. 全局 grep `system_context` 找所有引用点，登记（不在本步改，本步只改 schema + state.py 内部）：
   - subgraph.py（generate/llm_self_review 读 state.system_context）-> 06 步改
   - nodes/*.py prepare（写 system_context）-> 03/04/05 步改
   - chapter.py:183 generate_summary 读 system_context -> 04 步改
   - chapter_*_edit_subgraph.py -> 05/07 步改
   - chapter_plan_edit_subgraph.py -> 07 步改
   - brainstorm/consistency/prune -> 08 步改
   本步改 schema 后这些引用会 NameError/AttributeError--这是预期的"零兼容层"断裂点，后续步骤逐一修复。**本步不跑全量测试**（必然红），只确保 state.py 本身 lint/typecheck 过。

## Verify
1. `ruff check src/novel_workflow/state.py` 通过
2. `mypy --strict src/novel_workflow/state.py` 通过（注意 mypy 全项目有存量 import-not-found，state.py 本身应无新错）
3. grep 确认 system_context 在 state.py 已无残留（除注释提及）
4. **不跑全量测试**（schema 改后引用点未修，预期红，属正常）

## Notes
- 执行结果：✅ 完成
- 改动：state.py ReviewSubState + NovelState 两个 schema，删 system_context，加 system_prompt(L1)/context_prompt(L2)，task_prompt(L3) 保留
- 验证：ruff check 通过 / import 验证三字段就位、system_context 已删 / 修一处注释残留（current_arc_outline 注释）
- 预期红：68 处引用点（subgraph/nodes/edit子图/6测试）未修，将在 03-08 逐一修复。本步不跑全量测试（必然红，属零兼容层正常断裂）
- system_context 全局引用清单已登记（68 处，覆盖：state.py已改 / foundation.py×7 / chapter.py×3 / arc/chapter_plan/scene_beats/volumes/volume_cast/entity_cards / subgraph.py×4 / chapter_edit_subgraph×3 / chapter_plan_edit_subgraph×6 / generate_summary / 6 测试文件）

