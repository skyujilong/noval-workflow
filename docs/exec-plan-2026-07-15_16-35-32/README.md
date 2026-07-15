# 卷（Volume）结构化中间层 · 执行索引

**原计划**: `original-plan.md`
**执行时间戳**: 2026-07-15_16-35-32
**当前步骤**: 全部完成 ✓
**上一 compact 检查点**: 08-frontend-ui（已完成）
**Step 08 完成产物**：VolumeRibbon（顶部横条 + 详情弹窗）/ VolumesReviewForm（可编辑 review 表单）/ VolumeBoundaryGateForm（三选一 gate）— 全部通过 tsc/build/pytest 静态门禁。
**Step 09 状态**：用户手工场景 A-D 于 2026-07-15 验收通过，分卷（Volume）结构化中间层特性整体交付。

## 恢复命令
```
继续执行 docs/exec-plan-2026-07-15_16-35-32
```

## 步骤总览
| # | 名称 | 说明 |
|---|---|---|
| 01 | assumption-check | 闸门 E：跑一次 prepare_volumes 提示词验证 LLM 抽卷 JSON 输出稳定性 |
| 02 | schema-and-contracts | state.py 加 Volume + volumes 字段；interrupt_types.py 加枚举/映射 |
| 03 | volume-utils | volume_utils.py 章卷映射/位置卡/穿越判定 + 单测 |
| 04 | volumes-node | prompts/base.py 加 volumes_prompt；nodes/volumes.py 加 prepare/save + 单测 |
| 05 | volume-gate-node | nodes/volume_gate.py 加 volume_boundary_gate + 单测 |
| 06 | graph-and-prompt-injection | graph.py 装配 + 三处 prompt 头部注入 volume_position_card |
| 07 | frontend-types | 前端 Volume 类型 + interruptTypes 契约 |
| 08 | frontend-ui | VolumeRibbon + VolumesReviewForm + VolumeBoundaryGateForm |
| 09 | e2e-verify | 场景 A–D 手工端到端验收 |

## Compact 检查点
每完成 3 步（03/06/09）后提示 `/compact`。
