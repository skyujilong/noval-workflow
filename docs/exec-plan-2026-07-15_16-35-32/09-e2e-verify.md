# 09-e2e-verify

## Goal
后端 + 前端完成后，手工走一遍完整流程验收场景 A-D。此步不写代码，只做端到端验收和记录问题。

## Depends on
- 01-08 全部完成

## Do & Verify（场景 A-D）

### 场景 A：新建小说走到分卷 review
1. `make dev` 启动前后端
2. 新建小说 → 走脑爆 → 基础设定 → overall_outline 生成通过（4 卷式）
3. **应观察**：进入 `VolumesReviewForm`，LLM 抽出 4 卷（title/summary/setup_for_next/target_min/target_max），用户编辑后提交
4. **应观察**：顶部 `VolumeRibbon` 出现 4 卷横条，第一卷高亮 `in_progress`，其余 `planning`

### 场景 B：第一次 chapter_plan 触发 gate
1. 继续生成人物档案 → 一致性总审通过 → save_config 后走到第一次 `prepare_chapter_plan`
2. 假设 `total_chapters_written=0`, `CHAPTER_PLAN_WINDOW=40`, 第一卷 `target_min=22 target_max=28`
3. **应观察**：`window=[1,40]` 穿越卷一 `target_min=22, target_max=28` → `VolumeBoundaryGateForm` 弹出
4. 用户选"继续本卷" → chapter_plan 生成，40 条条目里 26-40 章的 purpose 应体现"卷二铺垫" 语义（LLM 拿到了卷位置卡）
5. **应观察**：生成完的 chapter_plan 里，第 25 章附近的 `ending_hook` 应含卷一 `setup_for_next` 元素

### 场景 C：卷边界调整回改
1. 写到卷一 target_max 附近时（触发下次 chapter_plan gate），选"在第 25 章收卷"
2. **应观察**：`state.volumes[0].actual_end=25, status="closed"`；`state.volumes[1].chapter_start=26, status="in_progress"`
3. 下一次 `arc_outline` 位置卡应显示"当前所在：第 2 卷 · 第 26 章起"
4. 顶部横条：卷一变 ✓ 显示 `1-25`，卷二变高亮

### 场景 D：arc_outline 拿到卷位置
1. 通过后端日志或 langgraph state 观察（也可用 chrome-devtools 拦 network）
2. **应观察**：`arc_outline` 的 task_prompt 头部含【当前卷位置】段

## Notes

### 2026-07-15 · Step 08 完成后落地状态
- 前端 3 组件已就位：
  - `frontend/src/components/novel/VolumeRibbon.tsx` — 顶部横条 + 只读详情对话框
  - `frontend/src/components/interrupts/VolumesReviewForm.tsx` — 可编辑 review 表单（title/summary/setup_for_next/target_min/target_max，chapter_start 联动重算，「通过」时通过 `updateThreadState` 覆写 `current_draft`）
  - `frontend/src/components/interrupts/VolumeBoundaryGateForm.tsx` — 三选一 gate 表单
- 契约衔接：
  - `HumanReviewForm.tsx` 在 `reviewType === "volumes" && threadId` 时 early-return delegate 到 `VolumesReviewForm`（其他 review_type 走原逻辑不变）
  - `InterruptHandler.tsx` 新增 `volume_boundary_gate` 分派 + 透传 `threadId`
  - `NovelWorkspace.tsx` 挂 `<VolumeRibbon state={state} />` 到右侧 aside 顶部（跨 interrupt/running/detail 各态可见），`threadId` 透传给 InterruptHandler
- 自动化门禁全绿：
  - `pnpm tsc --noEmit` → EXIT=0
  - `pnpm build` → 2747 modules, 2.06s
  - `uv run pytest -x -q` → 202 passed（含 56 volume 相关单测）

### 用户手工验收步骤（复现路径）
以下场景需实际 LLM 生成 + 用户交互，Step 09 状态保持 `runing` 直到用户逐场景确认通过。

**场景 A — 新建小说走到分卷 review + 顶部横条出现**
1. `make dev` 启动前后端
2. 新建小说 → 走脑爆 → 基础设定 → overall_outline 通过
3. 应观察：抽屉切换到「人工审核 · 分卷规划」，展示 N 卷可编辑卡片（每卷含 title 输入框 / summary textarea / setup_for_next textarea / target_min number / target_max number；chapter_start 灰色只读）
4. 改某卷 target_max（如卷 1 从 25 → 30）→ 应观察：卷 2 起的 chapter_start 立即联动重算
5. 点击「确认通过」→ 应观察：抽屉关闭，右侧顶部出现横条 4 卷条，卷 1 蓝色高亮 + ring，其余虚线未开启
6. 点击横条上某卷卡片 → 应观察：弹只读对话框展示 title/summary/卷尾 setup

**场景 B — 首次 chapter_plan 触发 gate**
1. 继续推进：人物档案审核 → 一致性总审通过 → save_config → 走到首次 `prepare_chapter_plan` 之前
2. 假设卷 1 `target_min=22 / target_max=28`，`total_chapters_written=0`，`CHAPTER_PLAN_WINDOW=40`
3. 应观察：`window=[1,40]` 命中卷 1 边界 → 弹出 `VolumeBoundaryGateForm`，顶部黄条列穿越点（卷 1 target_min=22 落入 / target_max=28 落入）
4. 应观察：三选一 radio 组，默认选中「继续本卷」；「在第 X 章收卷」的数字框预填 AI 建议中位（约 25），「延长 target_max」预填 target_max+5（约 33）
5. 点击「继续本卷」→ 提交 → 应观察：chapter_plan 生成 40 章条目；抽屉切换到「章节规划」审核卡片视图

**场景 C — 卷边界调整回改（收卷）**
1. 走到下一次 chapter_plan 前的 gate（`total_chapters_written` 已推进），触发新一轮 VolumeBoundaryGateForm
2. 选「在第 25 章收卷」（或自行改数字）→ 提交
3. 应观察后端 log / state：`volumes[0].actual_end=25`, `volumes[0].status="closed"`；`volumes[1].chapter_start=26`, `volumes[1].status="in_progress"`
4. 应观察前端横条：卷 1 变绿色 ✓「已收卷」+ 区间 `1-25`；卷 2 蓝色高亮进行中

**场景 D — arc_outline task_prompt 头部含【当前卷位置】**
1. 走到下一次 `prepare_arc_outline` 节点
2. 通过后端 log 或 `getThreadState(...).values.task_prompt` 观察
3. 应观察：task_prompt 头部包含 markdown 段落「【当前卷位置】- 当前所在：第 K 卷《...》」等 6 行字段

### 收尾条件
- 每场景由用户手工确认通过 → 更新本 Notes 记录 → `update_step_state.py ... 09-e2e-verify complate`
- 遇问题：回退到具体前端/后端 step 修补，本 step 保持 runing 不推进

