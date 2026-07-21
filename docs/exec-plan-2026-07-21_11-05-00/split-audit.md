# Split audit

## Coverage map
| 原始需求 | 步骤 | 状态 |
| --- | --- | --- |
| render.py 加 render_user + build_system snapshot 支持 | 01 | covered |
| state schema 三字段（删 system_context） | 02 | covered |
| 7 个 foundation prepare 迁移 | 03 | covered |
| chapter/titles/arc/scene_beats/volumes/volume_cast/chapter_plan prepare + generate_summary | 04 | covered |
| snapshot 类（foreshadowing/phase/initial_status）+ edit 子图 prepare | 05 | covered |
| generate/llm_self_review 走 render（解决自审丢资料） | 06 | covered |
| cp_entry 三处 LLM + edit_step 闭包 | 07 | covered |
| brainstorm/consistency/prune 独立 LLM 点 | 08 | covered |
| 验收脚本扩展覆盖全部 prepare | 09 | covered |
| 全量测试 + llm.py section 适配 + 最终验收 | 10 | covered |

## 调研风险点 -> 步骤映射
| 风险 | 处理步骤 |
| --- | --- |
| P0 entity_discover 身份缺失 | 05（snapshot/prepare 统一给身份） |
| P1 5 处双注（身份/伏笔/设定/outline/人物档案） | 03/04/05（prepare 层 include_identity=False + 删 prompt 方法开头 identity） |
| P2 cp_entry 三处共用 system_context | 07 |
| P2 arc_outline deep_character_view=True | 04 |
| P2 generate_summary 精简 L2 | 04 |
| P3 consistency 硬约束归一 HARD_CONTRACTS | 08 |
| P3 brainstorm 动态 system | 08 |
| P3 prune 子图走 context 管线评估 | 08 |

## 依赖与顺序修正
- 01(helper) 必须先于 03-08（prepare/generate 都依赖 render_user）
- 02(state schema) 必须先于 03（prepare 写新字段）
- 03-05(prepare) 必须先于 06(generate 消费新字段) -- 但 generate 是共用函数，06 改完 03-05 的字段才被消费。实际：02 改 schema -> 06 改 generate 读新字段 -> 03-05 逐个 prepare 填新字段。调整顺序为 01->02->06->03->04->05->07->08->09->10。
  **但** generate 改了若 prepare 还没填新字段会炸。折中：02+06 一起改（schema+generate 同步），用占位让旧 prepare 暂时跑通？不行，用户要零兼容层。
  **最终顺序**：01(helper) -> 02(schema) -> 03(foundation prepare) -> 04(chapter类prepare) -> 05(snapshot prepare) -> 06(generate/自审，此时所有 prepare 已产出新字段) -> 07(edit子图) -> 08(独立LLM) -> 09(验收) -> 10(测试)。generate 在 06 改，此时 03-05 已就绪，零兼容。

## Fixes made during audit
- 调整 06 位置：从第 6 步原意是"generate 改造"提前到所有 prepare 之后，避免 generate 读不到新字段。保持 06 序号但明确依赖 03-05 先完成。
- 确认无兼容层：schema 直接删 system_context，不保留过渡。

## Result
无已知遗漏。步骤顺序遵循构建依赖（helper->schema->prepare->generate->edit->独立点->验收->测试）。
