# 07-graph-wire

## Goal
把 `character_profiles_discover_step` 挂到 `graph.py`：imports 引入 + add_node + 拆边 `generate_summary → discover → chapter_edit_subgraph`。

## Depends on
- 06-subgraph-wire（`character_profiles_discover_step` 顶级对象可导入）

## Do
1. 打开 `src/novel_workflow/graph.py`。
2. **imports 追加**（第 65 行 `from noval_workflow.scene_beats_subgraph import scene_beats_step` 之后）：
   ```python
   from noval_workflow.character_profiles_discover_subgraph import character_profiles_discover_step
   ```
3. **add_node 追加**（第 135 行 `builder.add_node("scene_beats_step", scene_beats_step)` 之后另起 Phase 2.8 分节注释 + 节点声明）：
   ```python
   # Phase 2.8 — 角色档案发现（每章正文完成后自动，可跳步骤：generate_summary 之后、chapter_edit_subgraph 之前）
   builder.add_node("character_profiles_discover_step", character_profiles_discover_step)
   ```
4. **拆边**（第 265 行 `builder.add_edge("generate_summary", "chapter_edit_subgraph")`）拆成两段：
   ```python
   builder.add_edge("generate_summary", "character_profiles_discover_step")
   builder.add_edge("character_profiles_discover_step", "chapter_edit_subgraph")
   ```
5. **不改** `route_chapter_or_continue`（第 268-272 行）——章循环回跳仍到 `scene_beats_step`，下一章正文过后再次自然经过 discover 节点。

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && uv run python -c "
from noval_workflow.graph import graph
# 顶级 graph 编译成功即代表拓扑合法（节点齐 + 边有效 + state schema 桥接一致）
nodes = graph.get_graph().nodes
assert 'character_profiles_discover_step' in nodes, f'discover 节点未挂: {list(nodes.keys())}'
print('OK')
"`
2. 兜底 grep：`cd /Users/nbe01/workspace/noval-workflow-worktree-feature-character_profiles_discover && grep -n 'character_profiles_discover_step' src/novel_workflow/graph.py`
   期望至少 3 处命中（import + add_node + 两条 add_edge）。

## Notes
- 已完成：graph.py 追加 import（第 66 行）+ add_node（第 139 行）+ 拆 `generate_summary → chapter_edit_subgraph` 为两段（第 269-270 行）。
- Verify 通过：`graph.get_graph().nodes` 含 `character_profiles_discover_step`；grep 命中 4 处（import / add_node / 2 条 edge）。
