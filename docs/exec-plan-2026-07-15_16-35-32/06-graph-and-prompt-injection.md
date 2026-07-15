# 06-graph-and-prompt-injection

## Goal
把 Step 04-05 的节点接入 LangGraph 主图，并把 `volume_position_card(state)` 注入到 chapter_plan / arc_outline / chapter 三处 prompt 头部。这是本轮改动的**核心集成步骤**——完成后端到端流程理论上可跑。

## Depends on
- 04-volumes-node（prepare/save_volumes 已存在）
- 05-volume-gate-node（volume_boundary_gate 已存在）
- 03-volume-utils（volume_position_card 已存在）

## Do

### 6.1 图装配（`src/novel_workflow/graph.py`）

1. **插入 volumes 节点**：在 `save_overall_outline` 之后、`prepare_character_profiles` 之前
   ```
   save_overall_outline → prepare_volumes → review_volumes → save_volumes → prepare_character_profiles
   ```
   - 复用现有的 `review_subgraph`，`review_type="volumes"`
   - 与 `prepare_chapter_plan / review_chapter_plan / save_chapter_plan` 的注册模式对齐

2. **插入 volume_boundary_gate**：在 `chapter_plan_or_arc` 路由与 `prepare_chapter_plan` 之间
   ```
   ask_continue → chapter_plan_or_arc → volume_boundary_gate → prepare_chapter_plan → ...
   ```
   - 现有边（`graph.py:281-283`）：
     ```
     add_edge("prepare_chapter_plan", "review_chapter_plan")
     add_edge("review_chapter_plan", "save_chapter_plan")
     add_edge("save_chapter_plan", "prepare_arc_outline")
     ```
   - 新增：把 `chapter_plan_or_arc` 路由的 `prepare_chapter_plan` 目标改为 `volume_boundary_gate`，然后 `volume_boundary_gate → prepare_chapter_plan`

### 6.2 Prompt 注入卷位置卡

参考 `arc_outline_prompt`（`prompts/base.py:649-668`）已有的【本批位置卡】模式——`volume_position_card(state)` 返回一个 markdown 片段，直接拼在头部（若为空字符串则不注入）：

1. **`chapter_plan_prompt` / `render_chapter_plan_prompt`**（`prompts/base.py:720-1051`）：
   - 在头部现有的 written_section / locked_section / status_section 之前，最先注入 `volume_section = volume_position_card(state)`
   - 若为空则该 section 为空字符串，不影响原逻辑

2. **`arc_outline_prompt`**（`prompts/base.py:649-668`）：
   - 在现有【本批位置卡】之前叠加 `volume_section = volume_position_card(state)`

3. **`chapter_prompt`**（`prompts/base.py:472-615`）：
   - 在 `prepare_chapter` 组装 task_prompt 时（`nodes/chapter.py:65-118`）传入 volume 位置卡
   - 位置卡额外增强"卷内定位"信息：本章为卷内第 M/N 章（卷首/卷中/卷尾判定）
   - **简化实现**：直接在 chapter_prompt 头部插入 `volume_position_card(state)`；不做卷首/卷中/卷尾细分（后续可加）

4. **`context.py::build_foundation_context`** — **不改**。原因：如果把 volume 信息塞进 system_context，会污染所有 LLM 调用；只让具体生成节点在 task_prompt 层注入，保留精确性

### 6.3 补测试
1. 图装配集成测试：`tests/unit_tests/test_graph_volumes_integration.py`
   - 断言 `save_overall_outline` 的下一个节点是 `prepare_volumes`
   - 断言 `chapter_plan_or_arc` 路由到 `volume_boundary_gate`
   - 断言 `volume_boundary_gate` 的下一个节点是 `prepare_chapter_plan`
2. Prompt 注入测试：
   - 有 volumes 时，`chapter_plan_prompt` 输出包含"【当前卷位置】"
   - 无 volumes 时，`chapter_plan_prompt` 不含"【当前卷位置】"（向后兼容）
   - 同上验证 `arc_outline_prompt` 和 `chapter_prompt`

## Verify
1. `uv run pytest tests/unit_tests/test_graph_volumes_integration.py -x -q`
2. `uv run pytest tests/unit_tests/test_volumes_node.py tests/unit_tests/test_volume_gate.py tests/unit_tests/test_volume_utils.py -x -q`
3. 全量：`uv run pytest -x -q`
4. 图结构冒烟：
   ```
   uv run python -c "
   from noval_workflow.graph import graph
   nodes = list(graph.nodes)
   assert 'prepare_volumes' in nodes
   assert 'volume_boundary_gate' in nodes
   print('OK volumes/gate 节点已挂入图')
   "
   ```

## Notes
- 三处 prompt 注入需要 `NovelState` 传参，注意签名——`chapter_plan_prompt` 已经拿到 state；`arc_outline_prompt` 已经拿到 state；`chapter_prompt` 需要检查 `prepare_chapter` 里是否传入 state
- 如果 `chapter_prompt` 签名里没 state，改成传入 volume_position_card 字符串作为参数
- 图装配一定要跑冒烟测试，防止 LangGraph 编译期漏挂节点
- 达成 6-step 检查点后触发 /compact

### 执行结果 (2026-07-15)

**图装配 (`src/novel_workflow/graph.py`)**:
- 挂 4 个新节点：`prepare_volumes` / `review_volumes` / `save_volumes` / `volume_boundary_gate`
- 边接入：`save_overall_outline → prepare_volumes → review_volumes → save_volumes → prepare_character_profiles`（断掉原直连）
- gate 路由：`_route_after_save_config` 和 `route_continue_or_end` 原来指向 `prepare_chapter_plan` 的路径改指 `volume_boundary_gate`；`volume_boundary_gate → prepare_chapter_plan` 是普通透传边
- 无 volumes / 未穿越时 gate 直接 return {} 透传，向后兼容；有穿越时 interrupt 让用户决策

**Prompt 注入 (`src/novel_workflow/prompts/base.py`)**:
- `arc_outline_prompt(state)`：在【本批位置卡】之前注入 `volume_position_card(state)`（volumes 空时返回 ""，不影响）
- `render_chapter_plan_prompt(...)`：在 written_section 之前注入卷位置卡（所有题材 flavor builder 都走这里）
- `chapter_prompt(...)`：新增可选 `state` kwarg（默认 None，旧调用点/单测不受影响），非空且 volumes 非空时在标题下方注入
- `prepare_chapter`（`nodes/chapter.py`）：调用 `pack.chapter_prompt(..., state=state)` 传递

**新增测试 `tests/unit_tests/test_graph_volumes_integration.py`（10 单测）**:
- 图节点/边装配 3 条
- prompt 注入 6 条（3 处 × 有/无 volumes 双向）
- chapter_prompt 3 种情况：`state=None` / `state=有 state 但 volumes=[]` / `state=有 volumes`

### 验证
- `uv run pytest tests/unit_tests/test_graph_volumes_integration.py -x -q` → 10 passed
- `uv run pytest -x -q` 全量 → 202 passed（+10 from Step 05）
- 图冒烟：`from noval_workflow.graph import graph` 编译通过，57 节点齐全
