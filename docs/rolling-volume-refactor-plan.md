# 重构：滚动生成卷 + 卷即规划单元

## Context（为什么改）

现状：整书大纲被硬编码成"固定四卷"（`base.py:459-461`），而 chapter_plan 用"40 章机械滚动窗口 + STRIDE=10"独立平推、**不对齐卷边界**。两者错位，衍生出一堆补丁：`volume_boundary_gate`（跨卷检测）、`format_chapter_plan_volume_budget`（容量锚点）、`Volume.target_min/target_max`（预估额度）。

对**长篇连载**（几十万~百万字），"固定四卷"会把每卷撑到 80+ 章，卷不再是"完整小故事"，窗口对齐也失去意义。

目标：把"卷"变成**滚动生成**、且**卷即 chapter_plan 的规划单元**——开书只生成卷 1；写作推进到"下一批 arc_outline 触及/越过当前卷末章"时，先滚动规划下一卷。卷长由 **LLM 内容驱动产出**（15-50 章松护栏），人可在 review 抽屉干预。补丁全部删除。arc_outline（滚动细化、吸收漂移）不变。

## 已定决策

1. **护栏软硬度 = LLM 夹、人可破**：`save_volumes` 对 LLM 产出的章数 clamp 到 [15,50] + warning；人在 `review_volumes` 抽屉可突破。上下限走 env（`NOVEL_VOLUME_MIN/MAX_CHAPTERS`，默认 15/50）。
2. **planned_end 卷纲步产出**：`volumes_prompt` 让 LLM 每卷出 `title/summary/setup_for_next/chapters`(建议章数)；`index/chapter_start/planned_end/status` 由 `save_volumes` **权威赋值**（不信 LLM 的绝对章号）。`planned_end = chapter_start + clamp(chapters) - 1`。
3. **不做拆卷/合卷**：规划卷时一次生成好。
4. **CHAPTER_PLAN_ENABLED 整删**：新架构卷滚动是主干，"整条跳过 chapter_plan"退路会绕过卷触发而不自洽。
5. **`current_volume` 改章号映射优先**（修 Plan 发现的真 bug）：现在优先返回 `in_progress` 卷（`volume_utils.py:67-69`），滚动时会"提前翻卷"。改为 `volume_of_chapter(done+1)` 优先，`status` 退化为纯展示字段。

## 目标状态机

```
开书 Phase 1.5:  save_overall_outline → prepare_volumes(仅卷1) → review_volumes → save_volumes
                    └[route_after_save_volumes: written==0]→ prepare_character_cards → … → save_config
首卷展开:        save_config →(直边)→ prepare_chapter_plan(卷1 [1,planned_end]) → review → save_chapter_plan
                    → prepare_arc_outline → … → 正文循环
批末路由:        ask_continue →[route_continue_or_end]→
                    · 不续 → END
                    · 下一批末章(done+BATCH_SIZE) ≥ 当前卷末章 且无下一卷 → prepare_volumes(滚动态)
                    · 否则 → prepare_arc_outline
滚动卷N+1:       prepare_volumes(滚动态,生成1卷) → review_volumes → save_volumes
                    └[route_after_save_volumes: written>0]→ prepare_chapter_plan(展开N+1) → … → prepare_arc_outline
```

新路由 `route_continue_or_end`：
```
if not continue_writing: return END
cur = current_volume(volumes, done)            # = volume_of_chapter(done+1)
if cur is None: return "prepare_arc_outline"    # 冷启动兜底
has_next = any(v.index > cur.index for v in volumes)
vol_end = cur.actual_end if cur.actual_end is not None else cur.planned_end
if (not has_next) and (done + BATCH_SIZE >= vol_end): return "prepare_volumes"
return "prepare_arc_outline"
```
`has_next` 守卫防重复触发（N+1 已 append 后，接近 N 末章的后续批不再重复滚动）。`>=`（非 `>`）保证越卷前一批完成滚动、下一卷 chapter_plan 提前就位。

`route_after_save_volumes`（新，放 `nodes/volumes.py`）：`"prepare_character_cards" if written==0 else "prepare_chapter_plan"`。

## 分步实施（每步独立可跑通 + 可回滚 + 前后端契约同步）

过渡策略：先加 `planned_end` 与新逻辑、`target_min/target_max` 暂并存并优雅降级，**最后一步（Step 5）才删旧字段**。每步保证 `import graph` 通过、单测绿、前端 `pnpm typecheck` 过。

### Step 1 — 字段与护栏（纯加法，零行为变化）
- **后端**：`config.py` 加 `VOLUME_MIN_CHAPTERS`/`VOLUME_MAX_CHAPTERS`（复用 `_read_positive_int`）；`state.py` `Volume` 加 `planned_end:int=0`（保留 target_*）；`volume_utils.py` 的 `volume_of_chapter`/`current_volume`/`volume_position_card` 改为 **planned_end>0 用 planned_end，否则回退 `chapter_start+target_max-1`**；`current_volume` 改章号映射优先（决策 5）。
- **前端**：`frontend/src/lib/types.ts` `Volume` 加可选 `planned_end?:number`、`chapters?:number`（过渡期可选，不破坏现有）。
- **验证**：`uv run python -c "import noval_workflow.graph"`；`uv run pytest tests/unit_tests/test_volume_utils.py`（补 planned_end 用例；`test_current_volume_prefers_in_progress` 按新语义改）。

### Step 2 — volumes 双模 + 单卷契约 + 下游二分（前后端契约一起改）
- **后端**：
  - `nodes/volumes.py`：`prepare_volumes` 按 `not state.volumes` 分首次/滚动两套 prompt（滚动态输入 = overall_outline + 已有卷摘要 + 当前进度 + 上一卷 `setup_for_next`）；`save_volumes` 改**单卷**解析 + 权威赋值（首次→卷1 in_progress；滚动→上一卷 `actual_end=planned_end,status=closed`、append 新卷），章数 clamp[15,50]+warn；**只写 planned_end 不写 target_***；新增 `route_after_save_volumes`。
  - `prompts/base.py` `volumes_prompt`（471-511）：双模单卷契约，字段 `title/summary/setup_for_next/chapters`，写明 15-50。
  - `prompts/base.py` `overall_outline_prompt`（459-461）：**去四卷化**——删"四卷式/固定四段起承转合/划分四卷"，改成"全书方向性战略骨架 + 结局定位，不预设卷数/卷长"（滚动多少卷都有大方向可依）。
  - `prompts/review_shared.py` `VOLUMES_REVIEW_PROMPT`（94-115）：字段清单改新契约。
  - `graph.py:243`：`save_volumes` 直边 → `add_conditional_edges(route_after_save_volumes)`。
- **前端**（契约真源先改，让 TS 编译器标红其余点）：
  - `types.ts` `Volume`（35-45 + 注释 26-34）：删 `target_min/target_max`，改 `chapters:number` + `planned_end:number`。
  - `VolumesReviewForm.tsx`：两个 target 输入框 → 一个"本卷章数"框；`chapter_start`/`planned_end` 只读实时算展示（`planned_end=chapter_start+chapters-1`）；重写 `recomputeChapterStart`（拼接改 `nextStart=prev.chapter_start+prev.chapters`）、`validate`、窗口/汇总、`emptyVolume`默认。
  - `VolumesReviewCards.tsx`/`VolumesReadonly.tsx`/`VolumeRibbon.tsx`/`VolumesEditor.tsx`(placeholder 示例串)：同步。
- **验证**：后端重写 `test_volumes_node.py`（首/滚双模、单卷、planned_end 换算、clamp、append+close、route_after_save_volumes）；`test_graph_volumes_integration.py` save_volumes 下游断言改 conditional。前端 `pnpm typecheck && pnpm build`。端到端：跑 Phase 1.5 确认只生成卷 1 且带 planned_end、review 表单可编辑章数。

### Step 3 — `_plan_range` 改卷范围
- **后端**：`nodes/chapter_plan.py` `_plan_range`（95-104）返回**最大 index 卷**的 `[chapter_start, planned_end]`；`prepare_chapter_plan` 措辞、`render_chapter_plan_prompt` 文案（`base.py:1101-1104`）从"只规划 N 章/滚动窗口"改"规划整卷"；`merge_chapter_plan` 的 plan_end 语义=卷末（机制不变）。暂不动 `chapter_plan_last_regen_at`（Step 4 删）。
- **验证**：`test_chapter_plan_merge.py` plan_end 语义更新（卷 planned_end 数值场景）；补 `_plan_range` 首卷/滚动卷用例。

### Step 4 — 删 gate + 改路由触发（滚动正式激活）+ 前端删闸门
- **后端**：`nodes/chapter.py` `route_continue_or_end`（246-270）换三分逻辑（去 STRIDE/last_regen_at/ENABLED）；`graph.py` 删 `_route_after_save_config`→直边 `save_config→prepare_chapter_plan`、删 volume_boundary_gate 节点/边/import、`ask_continue` 目标 `volume_boundary_gate→prepare_volumes`；**删文件** `nodes/volume_gate.py`；删 `interrupt_types.py:113-116` `VOLUME_BOUNDARY_GATE`。
- **前端**：删 `VolumeBoundaryGateForm.tsx`；`interruptTypes.ts` 删 `VolumeDictSnapshot`/`VolumeGateExtendTargetMax`/`buildVolumeExtendResume`/`extend_target_max` action；分发层（`HumanReviewForm.tsx` 等）删对应分支。
- **验证**：**删** `test_volume_gate.py`；`test_graph_volumes_integration.py` 路由断言全改。前端 `pnpm build`。端到端：写到接近卷 1 末章 → 确认自动滚出卷 2 → 卷 2 chapter_plan 生成 → 继续写越卷批（越卷批各章按绝对章号精确取各自卷的 chapter_plan 条目）。

### Step 5 — 删 WINDOW/STRIDE/ENABLED + 容量锚点 + 冗余字段（不可逆语义点）
- **后端**：`config.py` 删 `CHAPTER_PLAN_WINDOW/STRIDE`（35-36,82-98）、`CHAPTER_PLAN_ENABLED`（80）；`volume_utils.py` 删 `find_boundary_crossings`+`BoundaryCrossing`、`format_chapter_plan_volume_budget`；`base.py` 删 budget import(18)+注入(1032-1033)+模板占位；`state.py` 删 `Volume.target_min/target_max`、`chapter_plan_last_regen_at`；`save_chapter_plan` 不再返回 `chapter_plan_last_regen_at`。
- **前端**：确认无 target_* 残留。
- **验证**：`grep -rn "target_max\|CHAPTER_PLAN_WINDOW\|CHAPTER_PLAN_STRIDE\|find_boundary_crossings\|chapter_plan_last_regen_at" src` 为空；全量单测；前端 build。**务必在 Step 1-4 全绿后再做。**

### Step 6 — 文案/注释收尾 + 完整端到端
- 更新 `state.py`（Volume/NovelState 注释）、`volume_utils.py`/`nodes/volumes.py` 顶注、chapter_plan 文案，去"四卷/target/WINDOW/STRIDE/滚动窗口"旧描述。
- 全量单测 + 一次完整端到端：开书 → 写满卷 1 → 滚卷 2 → 写越卷批，人工确认卷位置卡/章路线图一致。

## 关键文件

**后端**：`src/novel_workflow/graph.py`、`nodes/volumes.py`、`nodes/chapter.py`、`nodes/chapter_plan.py`、`volume_utils.py`、`state.py`、`config.py`、`prompts/base.py`、`prompts/review_shared.py`、`interrupt_types.py`；删 `nodes/volume_gate.py`。
**前端**：`frontend/src/lib/types.ts`、`components/interrupts/VolumesReviewForm.tsx`(最大)、`VolumesReviewCards.tsx`、`components/state/VolumesReadonly.tsx`、`VolumesEditor.tsx`、`components/novel/VolumeRibbon.tsx`、`lib/interruptTypes.ts`；删 `components/interrupts/VolumeBoundaryGateForm.tsx`。

## 风险与回滚

- **current_volume 提前翻卷**（头号）：Step 1 就落地章号映射优先。
- **越卷批章归属**：`prepare_chapter` 按 `item.chapter==chapter_num` 精确取，不拆卷，天然正确；前提是 N+1 chapter_plan 在写该批前已生成（路由 `>=` 保证）。
- **断点续写**：路由用 `total_chapters_written` 现算，无隐藏游标；删 `last_regen_at` 后无漂移记账。
- **老 checkpoint 迁移**：Step 5 删 target_* 后，旧快照带 target 键水合会 TypeError → 建议 feature 分支上新开书验证；如需兼容在飞旧工程，加"丢弃未知键"水合 shim（低优先，先 flag）。
- **前端 pnpm 版本**：本机 pnpm 8 vs 仓库 pnpm 10（见 memory），前端改动装依赖/build 时用最小改动法。
- **每步回滚**：Step 1-3 纯加/局部，单步 revert；Step 4 删 gate 建议单独 commit；Step 5 不可逆，最后做。

## 验证总纲

- 每步：后端 `uv run pytest tests/unit_tests/<相关>`；前端 `pnpm typecheck`。
- 收尾：全量单测 + 前端 build + 一次完整端到端（开书→卷1→滚卷2→越卷批），观察卷位置卡、章路线图、review 抽屉三处一致。
