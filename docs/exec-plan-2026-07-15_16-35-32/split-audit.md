# Split audit

## Coverage map
| Original requirement | Step(s) | Status |
| --- | --- | --- |
| 闸门 E — prepare_volumes JSON 输出稳定性验证 | 01-assumption-check | covered |
| 1.1 Volume dataclass + NovelState.volumes 字段 | 02-schema-and-contracts | covered |
| InterruptType.VOLUME_BOUNDARY_GATE 枚举 + volumes review_type 映射 | 02-schema-and-contracts | covered |
| 1.2 volume_utils.py（章卷映射 / 位置卡 / 穿越判定） | 03-volume-utils | covered |
| 1.3 prepare_volumes / save_volumes 节点 + volumes_prompt | 04-volumes-node | covered |
| 1.4 volume_boundary_gate 节点 | 05-volume-gate-node | covered |
| 1.4 graph.py 装配（prepare/review/save_volumes + volume_boundary_gate） | 06-graph-and-prompt-injection | covered |
| 1.5 三处 prompt 头部注入 volume_position_card（chapter_plan/arc_outline/chapter） | 06-graph-and-prompt-injection | covered |
| 2.1 前端 Volume 类型 + NovelState.volumes + REVIEW_TYPE_LABELS | 07-frontend-types | covered |
| 2.5 interruptTypes.ts VOLUME_BOUNDARY_GATE + 表单映射 | 07-frontend-types | covered |
| 2.2 顶部 VolumeRibbon 组件 | 08-frontend-ui | covered |
| 2.3 VolumesReviewForm | 08-frontend-ui | covered |
| 2.4 VolumeBoundaryGateForm | 08-frontend-ui | covered |
| NovelWorkspace 顶部挂载 VolumeRibbon | 08-frontend-ui | covered |
| 5.2 端到端手工验收（场景 A–D） | 09-e2e-verify | covered |
| 单元测试 test_volume_utils / test_volumes_node / test_volume_boundary_gate | 03/04/05 步各自内含 | covered |

## Fixes made during audit
- 将「假设验证」提为独立 Step 01（原计划注释在末尾建议）——防止后续实现基于错误假设跑偏。
- Prompt 注入合并入 Step 06 与图装配同批完成——避免装配好节点但 prompt 拿不到卷信息导致集成后仍失锚。
- 单测不单独成步——归到各自实现步的 Verify 环节，符合 execute-plan-plus「每步立即验证」原则。

## Result
No known omissions. Step order follows build dependencies: 假设验证 → schema/契约 → 工具函数 → 生成节点 → gate 节点 → 图装配+prompt → 前端契约 → 前端 UI → E2E。
