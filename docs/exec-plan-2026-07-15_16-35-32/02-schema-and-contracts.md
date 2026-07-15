# 02-schema-and-contracts

## Goal
落地数据契约：
1. 后端 `state.py` 加 `Volume` dataclass + `NovelState.volumes` 字段
2. 后端 `interrupt_types.py` 加 `VOLUME_BOUNDARY_GATE` 枚举 + `volumes` review_type 映射

先做契约层，让后续步骤都能 import 到这些类型/常量。

## Depends on
- 01-assumption-check（若 prompt 需要调整字段，会影响 Volume 结构）

## Do
1. 编辑 `src/novel_workflow/state.py`：
   - 新增 `Volume` dataclass（参见 original-plan.md §1.1）
   - `NovelState` 在 `overall_outline` 附近加 `volumes: list[Volume] = field(default_factory=list)` + 中文注释
   - **不加 reducer**：卷可能被删/合并，需要全量覆盖语义
2. 编辑 `src/novel_workflow/interrupt_types.py`：
   - `InterruptType` 加 `VOLUME_BOUNDARY_GATE = "volume_boundary_gate"`
   - `_REVIEW_TYPE_TO_INTERRUPT_TYPE` 加：`"volumes": InterruptType.REVIEW_GENERIC` （volumes review 走通用表单）
3. 验证 `NovelState` 老快照反序列化兼容：字段有默认值，Langraph checkpoint 旧数据缺 `volumes` 时走 `[]` 默认。
4. **不改** `frontend/`，前端契约放 Step 07 做。

## Verify
1. 后端类型/静态检查：
   ```
   cd /Users/nbe01/workspace/noval-workflow && uv run python -c "from src.novel_workflow.state import NovelState, Volume; s=NovelState(); assert s.volumes==[]; v=Volume(index=1,title='第一卷',chapter_start=1,target_min=20,target_max=25); print('OK', v)"
   ```
2. `uv run python -c "from src.novel_workflow.interrupt_types import InterruptType, review_type_to_interrupt_type; assert InterruptType.VOLUME_BOUNDARY_GATE == 'volume_boundary_gate'; assert review_type_to_interrupt_type('volumes').value == 'review_generic'; print('OK')"`
3. 若项目有 `pyright` / `mypy`：`uv run pyright src/novel_workflow/state.py src/novel_workflow/interrupt_types.py`
4. 若有 `make test`：`make test` 全绿

## Notes
- Volume 字段清单以 Step 01 验证后的 prompt 输出为准
- 遇到 Langgraph dataclass 反序列化坑（如 Annotated reducer），需在此步就绪

## 执行结果（2026-07-15）

**改动文件**：
- `src/novel_workflow/state.py`
  - 新增 `Volume` dataclass（放在 `EntityCard` 之前，`ChapterPlanItem` 之后）
  - `NovelState` 在 `character_profiles` 之后新增 `volumes: list[Volume] = field(default_factory=list)` + 中文注释
  - **关键**：注释里明确 `target_min/target_max = 本卷章数（数量）`，与 Step 01 语义修正对齐
- `src/novel_workflow/interrupt_types.py`
  - `InterruptType` 加 `VOLUME_BOUNDARY_GATE = "volume_boundary_gate"`
  - `_REVIEW_TYPE_TO_INTERRUPT_TYPE` 加 `"volumes": InterruptType.REVIEW_GENERIC`

**验证结果**：
- `NovelState().volumes == []` ✓
- Volume 双向序列化（`asdict` → `Volume(**d)`）等价 ✓
- 老快照兼容：不含 volumes 字段的旧 state 反序列化仍能拿到 `[]` 默认 ✓
- `VOLUME_BOUNDARY_GATE` 枚举值正确 + review_type 映射正确 ✓
- `uv run pytest -x -q` — 146 passed，全绿

**下一步**：Step 03 volume_utils.py 纯函数工具 + 单测
