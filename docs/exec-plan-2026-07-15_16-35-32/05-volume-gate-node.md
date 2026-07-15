# 05-volume-gate-node

## Goal
实现 `volume_boundary_gate` 节点：在 `prepare_chapter_plan` 之前插入的 interrupt 闸门。判断本次 chapter_plan 前瞻窗口是否穿越任一卷的 target_min/target_max，穿越则暂停执行、让用户三选一（继续本卷 / 在第 X 章收卷 / 延长 target_max），根据用户决策更新 `state.volumes`。

## Depends on
- 02-schema-and-contracts（VOLUME_BOUNDARY_GATE 枚举）
- 03-volume-utils（find_boundary_crossings / current_volume）
- 04-volumes-node（state.volumes 已生成）

## Do
1. 新增 `src/novel_workflow/nodes/volume_gate.py`：
   - `volume_boundary_gate(state: NovelState) -> dict`
   - 无 `state.volumes` 或未穿越时立即 return `{}`（no-op，让主链继续到 `prepare_chapter_plan`）
   - 穿越时构造 payload 并 `interrupt()`：
     ```python
     {
       "type": InterruptType.VOLUME_BOUNDARY_GATE.value,
       "window": [window_start, window_end],
       "crossings": [{"volume_index": ..., "kind": ..., "chapter": ...}, ...],
       "current_volume": {...},   # 当前卷的 dict 快照
       "next_volumes": [...],     # 后续未开启卷的 dict 快照（供用户看后续影响）
       "message": "本次长期规划窗口 [X, Y] 将穿越卷边界，请确认下一步：",
       "options": [
         {"action": "continue_current",  "label": "继续本卷（不改边界）"},
         {"action": "close_at",          "label": "在第 X 章收卷（AI 建议 X = target_min~target_max 中位值）", "suggested_chapter": ...},
         {"action": "extend_target_max", "label": "延长本卷 target_max 到 N（默认 +5）", "suggested_target_max": ...},
       ],
     }
     ```
   - 解析 decision（前端返回 dict：`{"action": ..., "chapter"?: int, "target_max"?: int}`）：
     - `continue_current` → 返回 `{}`（无变化）
     - `close_at` → 目标卷 `actual_end = chapter`, `status = "closed"`；下一卷 `chapter_start = chapter + 1`, `status = "in_progress"`；后续未开启卷 `chapter_start` 顺移（用 `target_max` 重新计算链）
     - `extend_target_max` → 目标卷 `target_max = new_val`；后续未开启卷 `chapter_start` 顺移
   - 返回 `{"volumes": updated_volumes}`
2. 新增 `tests/unit_tests/test_volume_gate.py`：
   - 空 volumes / 未穿越 → 无 interrupt，返回 `{}`
   - 三种 decision 分支：continue_current / close_at / extend_target_max，state.volumes 是否正确更新
   - close_at 后：目标卷 actual_end 正确、下一卷 in_progress、后续卷 chapter_start 顺移
   - extend_target_max 后：后续卷 chapter_start 顺移

## Verify
1. `uv run pytest tests/unit_tests/test_volume_gate.py -x -q`
2. `uv run pytest -x -q` 全量回归
3. 手动 sanity：
   ```
   uv run python -c "
   from noval_workflow.state import NovelState, Volume
   from noval_workflow.nodes.volume_gate import volume_boundary_gate
   vs = [Volume(index=1, title='卷1', chapter_start=1, target_min=22, target_max=28, status='in_progress'),
         Volume(index=2, title='卷2', chapter_start=29, target_min=35, target_max=45, status='planning')]
   state = NovelState(volumes=vs, total_chapters_written=0)
   # 未 monkey-patch interrupt 时会真的 interrupt——测试用 mock。这里只测无穿越路径：
   # 若 CHAPTER_PLAN_WINDOW=40，则窗口 [1,40] 穿卷1 target_min=22 max=28 → 会 interrupt
   # 只做 import 冒烟测
   print('OK import 冒烟')
   "
   ```

## Notes
- LangGraph 的 interrupt() 在测试里用 pytest monkeypatch 替换，参考 `test_scene_beats.py` 里现有测法
- 若发现 CHAPTER_PLAN_WINDOW 触达最后一卷 target_max 后仍要 gate 处理（一路走到全书完），需在 gate 里跳过 "无下一卷" case
- close_at 后重新计算后续卷 chapter_start 的公式：假设更新的卷 index=K, actual_end=X → volumes[K].chapter_start=X+1；随后从 K 到末尾遍历，chapter_start[i+1] = chapter_start[i] + target_max[i]（仅对未收卷）

### 执行结果 (2026-07-15)
- **nodes/volume_gate.py**（新增）：
  - `volume_boundary_gate(state)`：主节点函数
  - `_apply_close_at(volumes, target_index, close_chapter)`：纯函数
  - `_apply_extend_target_max(volumes, target_index, new_target_max)`：纯函数
  - `_volume_to_dict(v)`：dataclass → dict 供 interrupt payload
- **AI 建议章号公式**：`chapter_start + (target_min + target_max) // 2 - 1`（中位算绝对章号）
- **默认延长**：`target_max + 5`
- **decision 契约**：dict `{"action": ..., "chapter"?: int, "target_max"?: int}` 或字符串（老式兼容）
- **兜底**：未知 action 视为 continue_current（保守 no-op），日志 warning
- **tests/unit_tests/test_volume_gate.py**（新增）：14 单测，monkeypatch `interrupt`，覆盖：
  - 无 volumes / 无穿越 → no-op
  - 3 种 decision 分支各自 volumes 更新正确
  - suggested_chapter / suggested_target_max 缺 chapter/target_max 时的兜底
  - 字符串 decision 兼容
  - 未知 action 保守兜底
  - `_apply_close_at` / `_apply_extend_target_max` 纯函数校验（早于卷 start、找不到卷、低于 target_min 都 ValueError）

### 验证
- `uv run pytest tests/unit_tests/test_volume_gate.py -x -q` → 14 passed
- `uv run pytest -x -q` → 192 passed（+14 from Step 04）
- Sanity: 空 volumes 分支直接 return {} 无 interrupt
