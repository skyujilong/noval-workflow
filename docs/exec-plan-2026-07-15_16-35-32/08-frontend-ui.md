# 08-frontend-ui

## Goal
落地 3 个前端组件把分卷体验闭环：
1. `VolumeRibbon`：顶部 4 卷横条（当前卷高亮 + 已完成 ✓ + target range 徽章）
2. `VolumesReviewForm`：`review_type=volumes` 的专用编辑表单（每卷可编辑 title/summary/setup_for_next/target_min/target_max，chapter_start 自动推算只读）
3. `VolumeBoundaryGateForm`：VOLUME_BOUNDARY_GATE 三选一表单（继续本卷 / 收卷 / 延长 target_max）

## Depends on
- 07-frontend-types（Volume 类型契约已加）
- 后端 Step 04-06 已完成

## Do
### 8.1 `frontend/src/components/novel/VolumeRibbon.tsx`（新增）
- 从 `state.volumes` 读，为空时不渲染（返回 null）
- 布局：横向 flex，每卷一个卡片；`status="in_progress"` 高亮加粗；`status="closed"` 打 ✓ + 显示 `chapter_start-actual_end` 实际范围；`status="planning"` 虚线边框
- 每卷徽章：进行中显示 `已 N/(target_min~target_max) 章`（N = total_chapters_written - chapter_start + 1）；已收卷显示实际章数；未开启显示 target range
- 点击卡片打开只读详情弹窗（title / summary / setup_for_next）
- 挂到 `NovelWorkspace.tsx` 顶部（NovelDetail 之上）

### 8.2 `frontend/src/components/interrupts/VolumesReviewForm.tsx`（新增）
- `HumanReviewForm` 的专用变体：`review_type=volumes` 时前端路由到本组件
- 从 `current_draft`（LLM 输出 JSON 字符串）解析为 `Volume[]`；每卷一个可编辑卡片
- 字段：title / summary / setup_for_next / target_min / target_max 可编辑；chapter_start 前卷推算只读（前卷 target_max 变时联动重算）
- 提交时 JSON.stringify 回 current_draft，走通用 review resume 逻辑
- 布局参考 `ChapterPlanCards.tsx` 的逐条卡片范式

### 8.3 `frontend/src/components/interrupts/VolumeBoundaryGateForm.tsx`（新增）
- 展示：payload 里的 `current_volume` / `window` / `crossings` / `next_volumes`
- 三选一（radio button 组，参考 `EntryGateForm.tsx`）：
  - 继续本卷（默认高亮）— 提交 `{action: "continue_current"}`
  - 在第 [X] 章收卷 — 数字输入默认 payload.options[1].suggested_chapter，提交 `{action: "close_at", chapter: X}`
  - 延长本卷 target_max 到 [N] — 数字输入默认 payload.options[2].suggested_target_max，提交 `{action: "extend_target_max", target_max: N}`
- 通过 LangGraph resume 回传 decision

### 8.4 契约衔接
- `interruptTypes.ts::TYPE_TO_FORM[VOLUME_BOUNDARY_GATE]` 映射到 `"VolumeBoundaryGateForm"`
- `InterruptHandler.tsx` 加分支渲染 VolumeBoundaryGateForm（参考现有类型的分派）
- `HumanReviewForm.tsx` 在 `review_type === "volumes"` 时 delegate 到 `VolumesReviewForm`；否则走原逻辑

## Verify
1. `cd frontend && pnpm tsc --noEmit` → 无类型错误
2. `cd frontend && pnpm lint` 通过
3. `make dev` 启动前后端；打开浏览器（chrome-devtools MCP 或人工）：
   - 走脑爆 + 基础设定 → overall_outline 通过 → 应见 VolumesReviewForm（含 4 卷卡片可编辑）
   - 提交后顶部应现 VolumeRibbon（4 卷，第一卷高亮）
   - 触发首次 chapter_plan → 应见 VolumeBoundaryGateForm（穿越提示 + 三选一）
4. UI 验收句（Step 08 动手前，向用户确认）：
   - 触发场景：脑爆完 → 基础设定完 → 到「分卷规划」审核步骤 → 编辑卡片提交
   - 期望观察：顶部横条 4 卷出现，卷 1 高亮加粗
   - 完成条件：直到用户点击某个 gate 步骤或到下一批时看到 VolumeBoundaryGateForm 出现

## Notes
- `HumanReviewForm.tsx` 已有的通用 markdown 渲染 fallback 不能直接展示 JSON 数组——所以 volumes 必须走专用表单
- `VolumeRibbon` 只读；编辑入口一律走 review/gate 表单
- payload 字段名与 `nodes/volume_gate.py::volume_boundary_gate` 中构造的 payload 完全一致（window/crossings/current_volume/next_volumes/options）
