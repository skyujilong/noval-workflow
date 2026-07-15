# 04-volumes-node

## Goal
落地 `prepare_volumes` / `save_volumes` 节点，把 Step 01 已验证的 prompt 落到 `prompts/base.py`；`prepare_volumes` 生成 JSON 草稿，`save_volumes` 解析 JSON → 逐条造 `Volume` 实例并写入 `state.volumes`。走通用 `review_subgraph` 完成人工审核循环。

## Depends on
- 02-schema-and-contracts（Volume dataclass + volumes 字段）
- 03-volume-utils（复用类型；单测参考格式）
- Step 01 已产出 prompt 模板（在 `docs/.../scripts/probe_volumes_prompt.py` 中 `VOLUMES_PROMPT_TEMPLATE`）

## Do
1. 编辑 `src/novel_workflow/prompts/base.py`：
   - 新增 `def volumes_prompt(self, overall_outline: str) -> str` 方法（复用 Step 01 的 `VOLUMES_PROMPT_TEMPLATE`）
   - **关键**：字段语义、拼接公式、示例都严格照抄 Step 01 已验证版本
2. 参考 `prompts/base.py` 顶层导出模式，把 `volumes_prompt` 也暴露成模块级 `VOLUMES_PROMPT`（如果与其他 prompt 一致）
3. 新增 `src/novel_workflow/nodes/volumes.py`：
   - `prepare_volumes(state) -> dict`：
     - 调用 `build_foundation_context(state)` 获取 system_context
     - 从 `state.overall_outline` 生成 task_prompt（调用 `volumes_prompt`）
     - 返回 `{"system_context": ..., "task_prompt": ..., "review_type": "volumes", **reset_review_fields()}`
     - 用 `noval_workflow.llm.get_llm` 的调用惯例（参考现有 nodes/chapter_plan.py 或 nodes/scene_beats.py）
   - `save_volumes(state) -> dict`：
     - 用 `json_utils.parse_json_array_strict` 或类似方法解析 `state.current_draft`（JSON 数组）
     - 逐条造 `Volume(**item)`，第一卷 `status="in_progress"` 其余 `status="planning"`
     - 校验：`chapter_start`/`target_min`/`target_max` 类型 + 顺次拼接 + min ≤ max
     - 校验失败 → raise TypeError（触发通用 review 循环重生成，参见 ChapterPlanItem 惯例）
     - 返回 `{"volumes": volumes, **reset_review_fields()}`
4. 检查 `prompts/__init__.py` 是否需要导出 `volumes_prompt`（参考 chapter_plan 是否导出）
5. 新增 `tests/unit_tests/test_volumes_node.py`：
   - `prepare_volumes` 装配 task_prompt / review_type 正确
   - `save_volumes` 快乐路径：解析合法 JSON → 4 卷 Volume 实例 + 第一卷 in_progress
   - `save_volumes` 校验失败路径：字段缺失 / target_min > target_max / chapter_start 不连续 → 抛异常（触发 review 重生成）
   - 可选：`chapter_start` 与 `target_max` 拼接约束的边界测试

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow && uv run pytest tests/unit_tests/test_volumes_node.py -x -q`
2. 全量回归：`uv run pytest -x -q`
3. 手动 sanity（可选，因 Step 01 已跑通真实 LLM，此处只校验 prompt 组装）：
   ```
   uv run python -c "
   from noval_workflow.prompts import volumes_prompt   # 或从 base.py 具体路径
   text = volumes_prompt('# 卷一 xx...\n# 卷二 yy...')
   assert '【硬约束' in text or 'JSON 数组' in text
   print(text[:300])
   "
   ```

## Notes
- 记录 prompts/base.py 的方法名 + 模块级导出名（后续 Step 06 会 import）
- 记录 save_volumes 遇到的边界 case（LLM 输出畸形时的行为）

### 执行结果 (2026-07-15)
- **prompts/base.py**: `PromptPack.volumes_prompt(self, overall_outline)` 挂在 `overall_outline_prompt` 之后（line 416+），复用 Step 01 已验证的 `VOLUMES_PROMPT_TEMPLATE`（3/3 通过率）
- **无需模块级导出**：所有题材通过 `pack.volumes_prompt(...)` 调用，与 `chapter_plan_prompt` 一致；`prompts/__init__.py` 不改
- **nodes/volumes.py**（新增）：`prepare_volumes` / `save_volumes` 两个节点函数；`save_volumes` 校验包括：
  - JSON 非数组 / 空数组 → ValueError
  - 字段缺失/多余（Volume dataclass 严格 kwargs）→ ValueError
  - index 非 1..N 顺次 → ValueError
  - chapter_start 不接续（拼接约束）→ ValueError
  - target_min > target_max / <= 0 → ValueError
- **tests/unit_tests/test_volumes_node.py**（新增）：13 单测覆盖 prepare + save 所有失败路径 + 边界 case（含单卷/围栏输入）

### 验证
- `uv run pytest tests/unit_tests/test_volumes_node.py -x -q` → 13 passed
- `uv run pytest -x -q` 全量 → 178 passed（比 Step 03 165 多 13 条新单测）
- Sanity: `pack.volumes_prompt(...)` 生成 1256 字符提示词，硬约束段/JSON 示例齐备
