# 09-final-verify

## Goal
全量收口：pytest 全绿 + 前端 tsc 静默 + 端到端手动验证（可选，用户自行决定是否走完）。

## Depends on
- 01-08 全部 complate

## Do
1. **后端全量测试**：
   ```
   cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover
   uv run pytest tests/unit_tests/ -q
   ```
   期望：0 failed。若旧测试因新增 review_type 挂了（例如遍历所有 `_REVIEW_PROMPTS` 断言长度的测试），针对性补断言，不改本次业务代码。
2. **前端 tsc**：
   ```
   cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover/frontend
   pnpm exec tsc --noEmit
   ```
   期望：静默通过（0 errors）。
3. **graph 编译烟测**：
   ```
   cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run python -c "from noval_workflow.graph import graph; g = graph.get_graph(); assert 'character_profiles_discover_step' in g.nodes; print('graph OK')"
   ```
4. **端到端手动**（可选，用户在需要视觉验证时执行；本 step Verify 不强制要求跑完）：
   - 起 `make dev-backend` + `make dev-frontend`。
   - 从已进入 Phase 2 的 thread 走到章正文过审 → 观察前端右侧栏是否出现 `EntryGateForm`，标题「是否根据本章正文发现新角色 / 补充已知角色档案？」。
   - **空回车 skip**：应直接跳到 `chapter_edit_subgraph.arc_step`；`getThreadState().values.character_profiles` 不变。
   - **输入 yes**：走 generate → llm_self_review → human_review interrupt；前端 `HumanReviewForm` 标题「角色档案发现」，textarea 展示合流后完整档案；空回车通过后 `character_profiles` 已更新。

## Verify
1. Do 步骤 1–3 三条命令的输出摘要写入本 mini-plan 的 Notes。
2. 步骤 4 由用户手动完成后回写"已过端到端"或"暂不跑，后续需要时补"。

## Notes
- **后端 pytest 全量**：`uv run pytest tests/unit_tests/ -q` → **118 passed in 0.40s**（含新增 6 项）。
- **前端 tsc**：`pnpm exec tsc --noEmit`（frontend/）→ **静默通过（0 errors）**。
- **graph 编译烟测**：`from noval_workflow.graph import graph; ...` → **graph OK**（`character_profiles_discover_step` 已挂在拓扑内）。
- **端到端手动**（Do 步骤 4）：暂不跑，后续用户视需求手动验证；不阻断本步骤 complate。
