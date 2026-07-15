# 03-volume-utils

## Goal
实现纯函数工具库 `src/novel_workflow/volume_utils.py`：
- `volume_of_chapter(chapter_num, volumes)` — 章 → 卷映射
- `current_volume(volumes, total_chapters_written)` — 当前活跃卷
- `volume_position_card(state)` — 生成卷位置卡 markdown 片段（供 Step 06 三处 prompt 注入）
- `find_boundary_crossings(window_start, window_end, volumes)` — 判定 chapter_plan 窗口是否穿越卷边界

所有函数纯函数、无副作用，覆盖单测。

## Depends on
- 02-schema-and-contracts（依赖 Volume dataclass）

## Do
1. 创建 `src/novel_workflow/volume_utils.py`，实现四个函数（签名参照 original-plan.md §1.2）。
2. 关键规则：
   - `volume_of_chapter`：已收卷（`actual_end != None`）按 `[chapter_start, actual_end]` 判断；进行中卷（`actual_end == None`）：`chapter >= chapter_start` 且是最靠前的未收卷
   - `current_volume`：优先返回 `status == "in_progress"` 的第一卷；无则按 `total_chapters_written` 推断（第一个 `chapter_start > total_chapters_written` 前一卷）
   - `volume_position_card`：空 volumes 返回 `""`（无卷时不注入，保持向后兼容）
   - `find_boundary_crossings`：只统计"未收卷"（`actual_end == None`）的 `target_min` / `target_max`；已收卷不算穿越
3. 创建 `tests/test_volume_utils.py`，覆盖：
   - `volume_of_chapter` 边界：已收卷 / 进行中卷 / 章号超出所有卷 / 空 volumes
   - `find_boundary_crossings`：都不穿 / 穿 target_min / 穿 target_max / 都穿 / 空 volumes
   - `volume_position_card`：首卷 / 中卷 / 末卷 / 空 volumes / 无 in_progress 卷

## Verify
1. `cd /Users/nbe01/workspace/noval-workflow && uv run pytest tests/test_volume_utils.py -x -q`
2. 全部单测 pass
3. 手动 sanity：
   ```
   uv run python -c "
   from src.novel_workflow.state import Volume
   from src.novel_workflow.volume_utils import volume_of_chapter, find_boundary_crossings
   vs = [
     Volume(index=1, title='卷一', chapter_start=1, target_min=20, target_max=25, actual_end=None, status='in_progress'),
     Volume(index=2, title='卷二', chapter_start=26, target_min=25, target_max=30, actual_end=None, status='planning'),
   ]
   assert volume_of_chapter(5, vs).index == 1
   crossings = find_boundary_crossings(1, 40, vs)
   assert len(crossings) >= 2  # 至少穿卷一 target_min/target_max
   print('OK', crossings)
   "
   ```

## Notes
- 记录测试用例数量 + 覆盖率（如果项目已配 coverage）
- 记录 `volume_position_card` 的 markdown 格式最终定版（Step 06 会引用）

## 执行结果（2026-07-15）

**新增文件**：
- `src/novel_workflow/volume_utils.py` — 4 个纯函数 + `BoundaryCrossing` TypedDict
- `tests/unit_tests/test_volume_utils.py` — 19 个单测

**关键实现要点**：
- `volume_of_chapter` 已收卷用 `[chapter_start, actual_end]` 硬边界匹配；进行中卷用"最靠后的 chapter_start ≤ chapter_num"逻辑，容忍度为 `target_max * 2`
- `find_boundary_crossings` **只统计未收卷**——已收卷是硬边界，chapter_plan 窗口不再"穿越"它
- `find_boundary_crossings` 内部把 `(chapter_start, target_min, target_max)` 转成绝对章号：`min_chapter = chapter_start + target_min - 1`，`max_chapter = chapter_start + target_max - 1`
- `volume_position_card` 空 volumes 返回 `""`——未启用分卷的老小说不注入，向后兼容
- `current_volume` 优先返回 `status == "in_progress"` 的卷，无则按 `total_chapters_written + 1` 走 `volume_of_chapter`

**volume_position_card 格式定版**（Step 06 三处 prompt 引用）：
```
【当前卷位置】
- 当前所在：第 K 卷《{title}》（第 {chapter_start} 章起，目标 {target_min}-{target_max} 章）
- 本卷进度：本卷已完成 {done_in_vol}/({target_min}~{target_max}) 章
- 上一卷：{prev.title} —— {prev.summary}          # 首卷无此行
- 本卷主线：{cur.summary}
- 卷尾 setup：{cur.setup_for_next}                # setup_for_next 为空时无此行
- 下一卷预告：{next.title} 或 「（本卷为终卷）」
```

**验证结果**：
- `uv run pytest tests/unit_tests/test_volume_utils.py -x -q` — 19 passed
- `uv run pytest -x -q` — 165 passed（+19），全绿无回归

**下一步**：Step 04 volumes 节点 + prompts/base.py 添加 volumes_prompt
